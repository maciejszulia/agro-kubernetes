#!/usr/bin/env python3
"""Prepare a verified Alpine ARM64 cloud image and a key-only NoCloud seed."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

IMAGE = "generic_alpine-3.24.1-aarch64-uefi-tiny-r0.qcow2"
URL = "https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/cloud/" + IMAGE
SHA512 = "eb983aabed32fbf17ccca2ce5e0090d06d860caa52a93ed416d775f18b04d0d9a347366d0dae86ec2ae3923b6c728bb9ec1995fcb036dd63b467125e4b42a7dd"


def public_key(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    fields = lines[0].split() if len(lines) == 1 else []
    if len(fields) < 2 or fields[0] != "ssh-ed25519":
        raise ValueError("Expected exactly one OpenSSH Ed25519 public key line.")
    key = " ".join(fields[:2])
    with tempfile.TemporaryDirectory(prefix="agro-public-key-") as directory:
        check = Path(directory) / "key.pub"
        check.write_text(key + "\n", encoding="utf-8")
        subprocess.run(["ssh-keygen", "-l", "-f", str(check)], check=True,
                       capture_output=True, timeout=10)
    return key


def verified(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha512").hexdigest() == SHA512


def prepare_image(output):
    image = output / IMAGE
    if image.exists():
        if not verified(image):
            raise ValueError("Existing image checksum mismatch; refusing to overwrite it.")
        return image
    partial = output / (IMAGE + ".part")
    if not partial.exists() or not verified(partial):
        subprocess.run([
            "curl", "--fail", "--silent", "--show-error", "--location",
            "--retry", "3", "--retry-delay", "2", "--retry-max-time", "240",
            "--connect-timeout", "15", "--max-time", "120", "--continue-at", "-",
            "--output", str(partial), URL,
        ], check=True, capture_output=True, timeout=360)
    if not verified(partial):
        raise ValueError("Downloaded image checksum mismatch; image was not promoted.")
    os.link(partial, image)  # Atomic publication without replacing an existing image.
    partial.unlink()
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--name", default="xa2-01")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", args.name):
        raise ValueError("Name must be a lowercase DNS hostname label (1-63 characters).")
    key = public_key(args.public_key)
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    image = prepare_image(output)
    with tempfile.TemporaryDirectory(prefix=".cidata-", dir=output) as directory:
        staging = Path(directory)
        (staging / "meta-data").write_text(
            f"instance-id: agro-kubernetes-{args.name}-cloud-001\n"
            f"hostname: {args.name}\n"
            f"local-hostname: {args.name}\n", encoding="utf-8")
        (staging / "user-data").write_text(
            "#cloud-config\nuser:\n  name: alpine\n  shell: /bin/ash\n"
            f"ssh_authorized_keys:\n  - {json.dumps(key)}\n", encoding="utf-8")
        seed = staging / "seed.iso"
        subprocess.run([
            "bsdtar", "-cf", str(seed), "--format=iso9660",
            "--options", "iso9660:volume-id=CIDATA", "-C", str(staging),
            "meta-data", "user-data",
        ], check=True, capture_output=True, timeout=30)
        seed.replace(output / "seed.iso")
    print(f"SHA512 verified: {image}")
    print(f"CIDATA prepared: {output / 'seed.iso'}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # Report the failure without echoing key material or external command output.
        if isinstance(error, UnicodeError):
            detail = "The public key is not valid UTF-8 text."
        elif isinstance(error, ValueError):
            detail = str(error)
        elif isinstance(error, OSError):
            detail = os.strerror(error.errno) if error.errno else "Filesystem operation failed."
        elif isinstance(error, subprocess.CalledProcessError):
            detail = f"{Path(error.cmd[0]).name} exited with code {error.returncode}."
        elif isinstance(error, subprocess.TimeoutExpired):
            detail = f"{Path(error.cmd[0]).name} timed out."
        else:
            detail = "External command failed."
        print(f"Preparation failed: {detail}", file=sys.stderr)
        sys.exit(1)
