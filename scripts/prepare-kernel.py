#!/usr/bin/env python3
"""Verify and extract the pinned ARM64 kernel without installing its source APK."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

APK = "Podroid-v1.2.9-release.apk"
URL = "https://github.com/ExTV/Podroid/releases/download/v1.2.9/" + APK
SOURCE_COMMIT = "ce0121896b2895637ab1f656cbb0d75fa2874489"
APK_SHA256 = "3945c8c887f1df239501de6320fe5c8315bf9805029f530373d3244fee0d2a5f"
IMAGE_SHA256 = "c27d833649ea86473baedc24e8deb246c525a579c66f61b152d7505cc1a79969"
MEMBER = "assets/vmlinuz-virt"
REQUIRED_BUILTINS = """
HZ_100 VIRTIO VIRTIO_PCI VIRTIO_BLK VIRTIO_NET EXT4_FS DEVTMPFS DEVTMPFS_MOUNT
SERIAL_AMBA_PL011 SERIAL_AMBA_PL011_CONSOLE EFI_PARTITION CGROUPS MEMCG CGROUP_PIDS
NAMESPACES UTS_NS IPC_NS USER_NS PID_NS NET_NS OVERLAY_FS BRIDGE BRIDGE_NETFILTER
NETFILTER NF_CONNTRACK NF_NAT VXLAN VETH IP_NF_IPTABLES IP_NF_FILTER IP_NF_NAT
IP_NF_TARGET_MASQUERADE SECCOMP SECCOMP_FILTER ISO9660_FS
""".split()


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_apk(output):
    apk = output / APK
    if apk.exists():
        if file_hash(apk) != APK_SHA256:
            raise ValueError("Existing APK checksum mismatch; refusing to overwrite it.")
        return apk
    partial = output / (APK + ".part")
    if not partial.exists() or file_hash(partial) != APK_SHA256:
        subprocess.run([
            "curl", "--fail", "--silent", "--show-error", "--location",
            "--retry", "3", "--retry-delay", "2", "--retry-max-time", "240",
            "--connect-timeout", "15", "--max-time", "120", "--continue-at", "-",
            "--output", str(partial), URL,
        ], check=True, capture_output=True, timeout=360)
    if file_hash(partial) != APK_SHA256:
        raise ValueError("Downloaded APK checksum mismatch; APK was not promoted.")
    os.link(partial, apk)
    partial.unlink()
    return apk


def extract_kernel(apk):
    with zipfile.ZipFile(apk) as archive:
        image = gzip.decompress(archive.read(MEMBER))
    if image[0x38:0x3C] != b"ARMd":
        raise ValueError("Kernel lacks the ARM64 Image magic.")
    if hashlib.sha256(image).hexdigest() != IMAGE_SHA256:
        raise ValueError("Decompressed kernel checksum mismatch.")
    start = image.find(b"IKCFG_ST")
    end = image.find(b"IKCFG_ED", start + 8)
    if start < 0 or end < start + 8:
        raise ValueError("Kernel lacks a complete embedded configuration.")
    config = gzip.decompress(image[start + 8:end])
    options = dict(line.split("=", 1) for line in config.decode("utf-8").splitlines()
                   if line.startswith("CONFIG_") and "=" in line)
    required = {"CONFIG_" + option: "y" for option in REQUIRED_BUILTINS}
    required["CONFIG_HZ"] = "100"
    missing = [option for option, value in required.items() if options.get(option) != value]
    if missing:
        raise ValueError("Required kernel configuration missing: " + ", ".join(missing))
    return image, config


def prepare(output):
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    image, config = extract_kernel(prepare_apk(output))
    record = {
        "source_url": URL,
        "source_commit": SOURCE_COMMIT,
        "source_member": MEMBER,
        "component_license": "GPL-2.0",
        "apk_sha256": APK_SHA256,
        "image_sha256": IMAGE_SHA256,
        "image_bytes": len(image),
        "config_sha256": hashlib.sha256(config).hexdigest(),
        "kernel_config_gate": "passed",
        "reproducible_build_verified": False,
        "attestation_verified": False,
    }
    files = {"Image": image, "kernel.config": config,
             "verification.json": (json.dumps(record, indent=2) + "\n").encode()}
    for name, content in files.items():
        path = output / name
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f"Existing {name} differs; refusing to overwrite it.")
    with tempfile.TemporaryDirectory(prefix=".kernel-", dir=output) as directory:
        for name, content in files.items():
            path = output / name
            if path.exists():
                continue
            staged = Path(directory) / name
            staged.write_bytes(content)
            os.link(staged, path)
    return [output / name for name in files]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in prepare(args.output.expanduser().resolve()):
        print(f"Verified: {path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        print(f"Kernel preparation failed: {error}", file=sys.stderr)
        sys.exit(1)
