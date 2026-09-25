#!/usr/bin/env python3
"""Download and verify the pinned, unmodified K3s ARM64 launcher."""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys

BINARY = "k3s-arm64"
URL = "https://github.com/k3s-io/k3s/releases/download/v1.36.4%2Bk3s1/" + BINARY
SHA256 = "c920706346d5ad4e5cd3c7bf1bb09ce71ebe07fec829e513e40f1caf98aed8bb"


def verified(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == SHA256


def prepare(output):
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    binary = output / BINARY
    if binary.exists():
        if not verified(binary):
            raise ValueError("Existing K3s checksum mismatch; refusing to overwrite it.")
        return binary
    partial = output / (BINARY + ".part")
    if not partial.exists() or not verified(partial):
        subprocess.run([
            "curl", "--fail", "--silent", "--show-error", "--location",
            "--retry", "3", "--retry-delay", "2", "--retry-max-time", "240",
            "--connect-timeout", "15", "--max-time", "120", "--continue-at", "-",
            "--output", str(partial), URL,
        ], check=True, capture_output=True, timeout=360)
    if not verified(partial):
        raise ValueError("Downloaded K3s checksum mismatch; binary was not promoted.")
    partial.chmod(0o700)
    os.link(partial, binary)
    partial.unlink()
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    print("SHA256 verified:", prepare(args.output.expanduser().resolve()))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"K3s preparation failed: {error}", file=sys.stderr)
        sys.exit(1)
