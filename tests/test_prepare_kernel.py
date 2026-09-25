"""Verify kernel extraction and safety gates using a tiny local APK fixture."""

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare-kernel.py"
SPEC = importlib.util.spec_from_file_location("prepare_kernel", SCRIPT)
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)
CONFIG = ("CONFIG_HZ=100\n" + "".join("CONFIG_" + name + "=y\n" for name in """
HZ_100 VIRTIO VIRTIO_PCI VIRTIO_BLK VIRTIO_NET EXT4_FS DEVTMPFS DEVTMPFS_MOUNT
SERIAL_AMBA_PL011 SERIAL_AMBA_PL011_CONSOLE EFI_PARTITION CGROUPS MEMCG CGROUP_PIDS
NAMESPACES UTS_NS IPC_NS USER_NS PID_NS NET_NS OVERLAY_FS BRIDGE BRIDGE_NETFILTER
NETFILTER NF_CONNTRACK NF_NAT VXLAN VETH IP_NF_IPTABLES IP_NF_FILTER IP_NF_NAT
IP_NF_TARGET_MASQUERADE SECCOMP SECCOMP_FILTER ISO9660_FS
""".split())).encode()


def kernel(config=CONFIG):
    header = bytearray(64)
    header[0x38:0x3C] = b"ARMd"
    return bytes(header) + (b"IKCFG_ST" + gzip.compress(config, mtime=0) + b"IKCFG_ED"
                            if config is not None else b"")


class PrepareKernelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agro-kernel-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "output"
        self.source = self.root / "source.apk"
        constants = patch.multiple(prepare, URL=self.source.as_uri(), APK_SHA256="", IMAGE_SHA256="")
        constants.start()
        self.addCleanup(constants.stop)
        self.write_apk(kernel())

    def write_apk(self, image, member=prepare.MEMBER):
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr(member, gzip.compress(image, mtime=0))
            archive.writestr("assets/unrelated.txt", "must not be extracted")
        prepare.APK_SHA256 = prepare.file_hash(self.source)
        prepare.IMAGE_SHA256 = hashlib.sha256(image).hexdigest()

    def test_extract_only_kernel_and_verify_record(self):
        paths = prepare.prepare(self.output)
        self.assertEqual({path.name for path in paths}, {"Image", "kernel.config", "verification.json"})
        self.assertEqual({path.name for path in self.output.iterdir()},
                         {prepare.APK, "Image", "kernel.config", "verification.json"})
        self.assertEqual((self.output / "Image").read_bytes(), kernel())
        self.assertEqual((self.output / "kernel.config").read_bytes(), CONFIG)
        record = json.loads((self.output / "verification.json").read_text())
        self.assertEqual(record["image_sha256"], hashlib.sha256(kernel()).hexdigest())
        self.assertEqual(record["config_sha256"], hashlib.sha256(CONFIG).hexdigest())
        self.assertEqual(record["source_commit"], "ce0121896b2895637ab1f656cbb0d75fa2874489")
        self.assertFalse(record["reproducible_build_verified"])
        self.assertFalse(record["attestation_verified"])

    def test_reuse_valid_cache_without_source(self):
        prepare.prepare(self.output)
        before = {path.name: path.stat().st_mtime_ns for path in self.output.iterdir()}
        self.source.unlink()
        prepare.prepare(self.output)
        self.assertEqual({path.name: path.stat().st_mtime_ns for path in self.output.iterdir()}, before)

    def test_preserve_invalid_existing_files(self):
        for name in (prepare.APK, "Image", "kernel.config", "verification.json"):
            with self.subTest(file=name):
                output = self.root / name.replace(".", "-")
                output.mkdir()
                existing = output / name
                existing.write_bytes(b"preserve this existing file")
                with self.assertRaises(ValueError):
                    prepare.prepare(output)
                self.assertEqual(existing.read_bytes(), b"preserve this existing file")

    def test_reject_corrupt_download(self):
        self.source.write_bytes(b"not the pinned APK")
        with self.assertRaises(ValueError):
            prepare.prepare(self.output)
        self.assertFalse((self.output / prepare.APK).exists())
        self.assertFalse((self.output / "Image").exists())

    def test_resume_partial_apk(self):
        self.output.mkdir()
        partial = self.output / (prepare.APK + ".part")
        partial.write_bytes(self.source.read_bytes()[:8])
        prepare.prepare(self.output)
        self.assertFalse(partial.exists())
        self.assertEqual((self.output / "Image").read_bytes(), kernel())

    def test_reject_missing_kernel_member(self):
        self.write_apk(kernel(), member="assets/other-kernel")
        with self.assertRaises(KeyError):
            prepare.prepare(self.output)
        self.assertFalse((self.output / "Image").exists())

    def test_reject_invalid_magic_and_kernel_checksum(self):
        for case in ("magic", "checksum"):
            with self.subTest(case=case):
                if case == "magic":
                    self.write_apk(kernel().replace(b"ARMd", b"FAIL", 1))
                else:
                    self.write_apk(kernel())
                    prepare.IMAGE_SHA256 = "0" * 64
                with self.assertRaises(ValueError):
                    prepare.prepare(self.root / case)

    def test_reject_missing_or_corrupt_embedded_config(self):
        for label, image in (("missing", kernel(None)), ("corrupt", kernel(None) + b"IKCFG_STbadIKCFG_ED")):
            with self.subTest(case=label):
                self.write_apk(image)
                with self.assertRaises((ValueError, OSError)):
                    prepare.prepare(self.root / label)
                self.assertFalse((self.root / label / "Image").exists())

    def test_require_hz100_and_builtin_features(self):
        for option in ("HZ=100", "VIRTIO_BLK=y", "MEMCG=y", "OVERLAY_FS=y", "VXLAN=y", "SECCOMP_FILTER=y"):
            with self.subTest(option=option):
                config = CONFIG.replace(("CONFIG_" + option).encode(),
                                        ("CONFIG_" + option.split("=")[0] + "=m").encode())
                self.write_apk(kernel(config))
                output = self.root / option.split("=")[0]
                with self.assertRaises(ValueError):
                    prepare.prepare(output)
                self.assertFalse((output / "Image").exists())


if __name__ == "__main__":
    unittest.main()
