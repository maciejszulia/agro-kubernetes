"""Validate built-kernel inputs without starting QEMU or changing phone state."""

import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/termux-kernel-start.sh"
VALIDATOR = SCRIPT.read_text().split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
BOOT_FEATURES = runpy.run_path(str(ROOT / "scripts/prepare-kernel.py"))["REQUIRED_BUILTINS"]
NETWORK_FEATURES = """
IP_NF_TARGET_REJECT NETFILTER_XT_MATCH_MULTIPORT NETFILTER_XT_MATCH_STATISTIC
NETFILTER_XT_MATCH_IPVS IP_SET IP_SET_HASH_IP IP_SET_HASH_NET NETFILTER_XT_SET
NETFILTER_XT_MATCH_PHYSDEV NETFILTER_XT_MATCH_LIMIT NETFILTER_XT_TARGET_NFLOG
""".split()


class TermuxKernelValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agro-launcher-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / "built-kernel"
        self.directory.mkdir()
        image = bytearray(64)
        image[0x38:0x3C] = b"ARMd"
        (self.directory / "Image").write_bytes(image)
        self.config = ("".join("CONFIG_" + name + "=y\n" for name in BOOT_FEATURES + NETWORK_FEATURES)
                       + 'CONFIG_HZ=100\nCONFIG_LOCALVERSION="-agro1"\n'
                       + '# CONFIG_LOCALVERSION_AUTO is not set\n')
        (self.directory / "kernel.config").write_text(self.config)
        self.metadata = {
            "release": "7.1.5-agro1",
            "source_sha256": "22a0196b3cbcdf34dc27b77561f4d040585fd3447edc9ab3531a1ac79e3041e7",
            "baseline_config_sha256": "c8f5253a5ae005a3a6767fd732267b24e562548fd5440fb6bed3eccd8f572297",
        }
        self.write_metadata()

    def write_metadata(self):
        for name, key in (("Image", "image_sha256"), ("kernel.config", "resolved_config_sha256")):
            self.metadata[key] = hashlib.sha256((self.directory / name).read_bytes()).hexdigest()
        (self.directory / "build-metadata.json").write_text(json.dumps(self.metadata))

    def validate(self):
        return subprocess.run([sys.executable, "-B", "-", str(self.directory)], input=VALIDATOR,
                              capture_output=True, text=True, timeout=10)

    def test_accept_consistent_build_without_hardcoded_image_hash(self):
        first = self.validate()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout.strip(), str(self.directory / "Image"))
        with (self.directory / "Image").open("ab") as stream:
            stream.write(b"different locally recorded build")
        self.write_metadata()
        second = self.validate()
        self.assertEqual(second.returncode, 0, second.stderr)

    def test_reject_corrupt_image_config_and_missing_magic(self):
        for name in ("Image", "kernel.config"):
            with self.subTest(file=name):
                path = self.directory / name
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                self.assertNotEqual(self.validate().returncode, 0)
                path.write_bytes(original)
        (self.directory / "Image").write_bytes(b"no ARM64 header")
        self.write_metadata()
        self.assertNotEqual(self.validate().returncode, 0)

    def test_reject_unsupported_metadata_identity(self):
        for name in ("release", "source_sha256", "baseline_config_sha256"):
            with self.subTest(field=name):
                original = self.metadata[name]
                self.metadata[name] = "unsupported"
                self.write_metadata()
                self.assertNotEqual(self.validate().returncode, 0)
                self.metadata[name] = original
        (self.directory / "build-metadata.json").write_text("[]")
        self.assertNotEqual(self.validate().returncode, 0)

    def test_reject_missing_network_and_boot_requirements(self):
        changes = [(name + "=y", name + "=m") for name in NETWORK_FEATURES]
        changes += [("HZ=100", "HZ=250"), ("VIRTIO_BLK=y", "VIRTIO_BLK=m"),
                    ("SERIAL_AMBA_PL011_CONSOLE=y", "SERIAL_AMBA_PL011_CONSOLE=n")]
        for original, replacement in changes:
            with self.subTest(option=original):
                (self.directory / "kernel.config").write_text(
                    self.config.replace("CONFIG_" + original, "CONFIG_" + replacement))
                self.write_metadata()
                self.assertNotEqual(self.validate().returncode, 0)

    def test_invalid_arguments_and_files_fail_before_side_effects(self):
        tools = self.root / "bin"
        tools.mkdir()
        sentinel = self.root / "mutation-attempt"
        for name in ("qemu-img", "qemu-system-aarch64", "termux-wake-lock"):
            tool = tools / name
            tool.write_text('#!/bin/sh\nprintf attempted > "$LAUNCHER_TEST_SENTINEL"\nexit 99\n')
            tool.chmod(0o700)
        environment = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
                           LAUNCHER_TEST_SENTINEL=str(sentinel))
        (self.directory / "kernel.config").unlink()
        for arguments in ([str(self.directory)], [str(self.root / "missing")], [""],
                          ["--unsupported"], [str(self.directory), "extra"]):
            with self.subTest(arguments=arguments):
                result = subprocess.run(["bash", str(SCRIPT), *arguments], env=environment,
                                        capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(sentinel.exists(), "Invalid input reached a mutating command")
        self.assertEqual((self.directory / "Image").stat().st_size, 64)


if __name__ == "__main__":
    unittest.main()
