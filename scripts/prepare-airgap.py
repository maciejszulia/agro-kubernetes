#!/usr/bin/env python3
"""Derive the fixed ARM64 lab image subset from the pinned official K3s archive."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tarfile
import tempfile

SOURCE_SHA256 = "d84268705e70019d76f4ef1c27cbb9d0bf480486e1d216103ebc732cfbd35bbb"
IMAGES = {
    "docker.io/rancher/mirrored-library-busybox:1.37.0":
        "sha256:101b4afd76732482eff9b95cae5f94bcf295e521fbec4e01b69c5421f3f3f3e5",
    "docker.io/rancher/mirrored-pause:3.10.2":
        "sha256:f548e0e8e3dc1896ca956272154dde3314e8cc4fde0a57577ee9fa1c63f5baf4",
    "docker.io/rancher/mirrored-coredns-coredns:1.14.6":
        "sha256:900f9c109f7a33545d3c811516e8376df9019147b750f5ce3e254468769176ea",
}
INDEX_TYPES = {"application/vnd.oci.image.index.v1+json",
               "application/vnd.docker.distribution.manifest.list.v2+json"}
MANIFEST_TYPES = {"application/vnd.oci.image.manifest.v1+json",
                  "application/vnd.docker.distribution.manifest.v2+json"}


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def selected_entries(archive):
    entries = archive.getmembers()
    members = {entry.name: entry for entry in entries}
    if len(members) != len(entries):
        raise ValueError("Duplicate archive paths")
    retained = {}

    def read(name):
        member = members.get(name)
        if member is None or not member.isfile():
            raise ValueError("Missing or nonregular selected entry: " + name)
        return archive.extractfile(member).read()

    def blob(descriptor):
        digest, size = descriptor["digest"], descriptor["size"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or type(size) is not int or size < 0:
            raise ValueError("Invalid blob descriptor")
        name = "blobs/sha256/" + digest[7:]
        if name not in retained:
            retained[name] = read(name)
        data = retained[name]
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest[7:]:
            raise ValueError("Blob size or checksum mismatch: " + digest)
        return name, data

    layout = read("oci-layout")
    if json.loads(layout).get("imageLayoutVersion") != "1.0.0":
        raise ValueError("Unsupported OCI layout")
    index = json.loads(read("index.json"))
    if index.get("schemaVersion") != 2 or index.get("mediaType") not in INDEX_TYPES:
        raise ValueError("Unsupported outer image index")
    chosen, expected_docker = [], {}
    for tag, digest in sorted(IMAGES.items()):
        matches = [item for item in index["manifests"]
                   if item.get("annotations", {}).get("io.containerd.image.name") == tag]
        if len(matches) != 1 or matches[0]["digest"] != digest:
            raise ValueError("Missing, duplicate or unexpected pinned image: " + tag)
        top = matches[0]
        root = json.loads(blob(top)[1])
        if (top["mediaType"] not in INDEX_TYPES or root.get("schemaVersion") != 2
                or root.get("mediaType") != top["mediaType"]):
            raise ValueError("Unsupported image index: " + tag)
        arm64 = [item for item in root["manifests"]
                 if item.get("platform", {}).get("os") == "linux"
                 and item.get("platform", {}).get("architecture") == "arm64"
                 and item.get("platform", {}).get("variant", "v8") == "v8"]
        if len(arm64) != 1:
            raise ValueError("Expected exactly one linux/arm64 manifest: " + tag)
        child = arm64[0]
        manifest = json.loads(blob(child)[1])
        if (child["mediaType"] not in MANIFEST_TYPES or manifest.get("schemaVersion") != 2
                or manifest.get("mediaType") != child["mediaType"]):
            raise ValueError("Unsupported ARM64 manifest: " + tag)
        config_name, config_data = blob(manifest["config"])
        config = json.loads(config_data)
        if (config.get("os"), config.get("architecture")) != ("linux", "arm64"):
            raise ValueError("Image configuration is not linux/arm64: " + tag)
        layers = [blob(layer)[0] for layer in manifest["layers"]]
        expected_docker[tag.removeprefix("docker.io/")] = (config_name, layers)
        chosen.append(top)

    compatible = {}
    for record in json.loads(read("manifest.json")):
        for tag in record.get("RepoTags", []):
            name = tag.removeprefix("docker.io/")
            if name not in expected_docker:
                continue
            if name in compatible or (record["Config"], record["Layers"]) != expected_docker[name]:
                raise ValueError("Inconsistent Docker-compatible image record: " + tag)
            compatible[name] = dict(record, RepoTags=[tag])
    if set(compatible) != set(expected_docker):
        raise ValueError("Missing Docker-compatible image records")
    # Preserve image-index blobs, including absent non-ARM64 references, byte-for-byte.
    retained["oci-layout"] = layout
    retained["index.json"] = encoded(dict(index, manifests=chosen))
    retained["manifest.json"] = encoded([compatible[name] for name in sorted(compatible)])
    return retained


def prepare(source, output):
    if output.exists() and output.samefile(source):
        raise ValueError("Source and output must be different files")
    if sha256(source) != SOURCE_SHA256:
        raise ValueError("Official source archive checksum mismatch")
    with tarfile.open(source, "r:") as archive:
        entries = selected_entries(archive)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix="." + output.name + ".", suffix=".part", dir=output.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                for path, data in sorted(entries.items()):
                    member = tarfile.TarInfo(path)
                    member.size, member.mode, member.mtime = len(data), 0o644, 0
                    member.uid = member.gid = 0
                    member.uname = member.gname = ""
                    archive.addfile(member, io.BytesIO(data))
        if output.exists():
            if sha256(output) != sha256(temporary):
                raise ValueError("Existing output differs; refusing to overwrite it")
        else:
            os.link(temporary, output)
    finally:
        temporary.unlink()
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = prepare(args.source.expanduser().resolve(), args.output.expanduser().absolute())
    print("Verified official source SHA256:", SOURCE_SHA256)
    print(f"Derived ARM64 archive: {output} ({output.stat().st_size} bytes)")
    print("Derived SHA256:", sha256(output))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as error:
        print("Air-gap preparation failed:", error, file=sys.stderr)
        sys.exit(1)
