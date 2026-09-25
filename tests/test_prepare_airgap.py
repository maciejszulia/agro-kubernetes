"""Exercise subset integrity and reproducibility with small local OCI archives."""

import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare-airgap.py"
SPEC = importlib.util.spec_from_file_location("prepare_airgap", SCRIPT)
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)
INDEX = "application/vnd.oci.image.index.v1+json"
MANIFEST = "application/vnd.oci.image.manifest.v1+json"


def blob_path(descriptor):
    return "blobs/sha256/" + descriptor["digest"].split(":")[1]


class PrepareAirgapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agro-airgap-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.output = self.root / "official.tar", self.root / "derived.tar"
        self.members, self.roots, self.layers, self.pins = {}, {}, {}, {}
        self.index = {"schemaVersion": 2, "mediaType": INDEX, "manifests": []}
        self.docker = []
        for tag in sorted(prepare.IMAGES):
            config = self.add_blob(json.dumps({"os": "linux", "architecture": "arm64", "test": tag}).encode(),
                                   "application/vnd.oci.image.config.v1+json")
            layer = self.add_blob(gzip.compress(tag.encode(), mtime=0),
                                  "application/vnd.oci.image.layer.v1.tar+gzip")
            self.layers[tag] = layer
            leaf = self.add_blob(json.dumps({"schemaVersion": 2, "mediaType": MANIFEST,
                                             "config": config, "layers": [layer]}).encode(), MANIFEST)
            leaf["platform"] = {"os": "linux", "architecture": "arm64", "variant": "v8"}
            absent = {"mediaType": MANIFEST, "digest": "sha256:" + "f" * 64, "size": 100,
                      "platform": {"os": "linux", "architecture": "amd64"}}
            descriptor = self.add_blob(json.dumps({"schemaVersion": 2, "mediaType": INDEX,
                                                    "manifests": [leaf, absent]}).encode(), INDEX)
            descriptor["annotations"] = {"io.containerd.image.name": tag,
                                          "org.opencontainers.image.ref.name": tag.rsplit(":", 1)[1]}
            self.index["manifests"].append(descriptor)
            self.roots[tag], self.pins[tag] = descriptor, descriptor["digest"]
            self.docker.append({"Config": blob_path(config), "Layers": [blob_path(layer)],
                                "RepoTags": [tag.removeprefix("docker.io/")]})
        unused = self.add_blob(b"unselected image metadata", INDEX)
        unused["annotations"] = {"io.containerd.image.name": "docker.io/rancher/mirrored-library-traefik:3.7.8"}
        self.index["manifests"].append(unused)
        self.docker.append({"Config": "absent", "Layers": ["absent"],
                            "RepoTags": ["rancher/mirrored-library-traefik:3.7.8"]})
        self.members["oci-layout"] = b'{"imageLayoutVersion":"1.0.0"}\n'
        constants = patch.multiple(prepare, IMAGES=self.pins, SOURCE_SHA256="")
        constants.start()
        self.addCleanup(constants.stop)
        self.pack()

    def add_blob(self, data, media_type):
        descriptor = {"mediaType": media_type, "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                      "size": len(data)}
        self.members[blob_path(descriptor)] = data
        return descriptor

    def replace_root(self, tag, value):
        descriptor = self.roots[tag]
        del self.members[blob_path(descriptor)]
        descriptor.update(self.add_blob(json.dumps(value).encode(), INDEX))
        self.pins[tag] = descriptor["digest"]

    def pack(self, reverse=False, duplicate=None):
        self.members["index.json"] = json.dumps(self.index).encode()
        self.members["manifest.json"] = json.dumps(self.docker).encode()
        with tarfile.open(self.source, "w", format=tarfile.USTAR_FORMAT) as archive:
            names = sorted(self.members, reverse=reverse)
            if duplicate:
                names.append(duplicate)
            for name in names:
                member = tarfile.TarInfo(name)
                member.size, member.mode, member.mtime = len(self.members[name]), 0o600, 123 if reverse else 456
                member.uid = member.gid = 1000
                archive.addfile(member, io.BytesIO(self.members[name]))
        prepare.SOURCE_SHA256 = prepare.sha256(self.source)

    def test_arm64_subset_preserves_roots_and_missing_other_platform_references(self):
        prepare.prepare(self.source, self.output)
        with tarfile.open(self.output) as archive:
            entries = archive.getmembers()
            data = {entry.name: archive.extractfile(entry).read() for entry in entries}
        self.assertEqual(len(data), 15)
        self.assertEqual([entry.name for entry in entries], sorted(data))
        self.assertTrue(all((entry.uid, entry.gid, entry.mode, entry.mtime, entry.uname, entry.gname)
                            == (0, 0, 0o644, 0, "", "") for entry in entries))
        selected = json.loads(data["index.json"])["manifests"]
        self.assertEqual({item["annotations"]["io.containerd.image.name"] for item in selected}, set(self.pins))
        self.assertEqual(len(json.loads(data["manifest.json"])), 3)
        for descriptor in selected:
            self.assertEqual(data[blob_path(descriptor)], self.members[blob_path(descriptor)])
            original = json.loads(data[blob_path(descriptor)])
            arm, missing = original["manifests"]
            self.assertNotIn(blob_path(missing), data)
            leaf = json.loads(data[blob_path(arm)])
            for child in (arm, leaf["config"], *leaf["layers"]):
                contents = data[blob_path(child)]
                self.assertEqual(len(contents), child["size"])
                self.assertEqual(hashlib.sha256(contents).hexdigest(), child["digest"].split(":")[1])

    def test_deterministic_output_ignores_source_order_and_tar_metadata(self):
        prepare.prepare(self.source, self.output)
        self.index["manifests"].reverse()
        self.docker.reverse()
        self.pack(reverse=True)
        other = self.root / "second.tar"
        prepare.prepare(self.source, other)
        self.assertEqual(other.read_bytes(), self.output.read_bytes())

    def test_reject_changed_official_source_before_output(self):
        with self.source.open("r+b") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError, "source archive checksum"):
            prepare.prepare(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_reject_corrupt_selected_blob(self):
        path = blob_path(next(iter(self.layers.values())))
        data = self.members[path]
        self.members[path] = bytes([data[0] ^ 255]) + data[1:]
        self.pack()
        with self.assertRaisesRegex(ValueError, "Blob size or checksum"):
            prepare.prepare(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_reject_missing_selected_layer(self):
        del self.members[blob_path(next(iter(self.layers.values())))]
        self.pack()
        with self.assertRaisesRegex(ValueError, "Missing or nonregular selected entry"):
            prepare.prepare(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_reject_absent_required_platform(self):
        tag = next(iter(self.roots))
        root = json.loads(self.members[blob_path(self.roots[tag])])
        root["manifests"] = [root["manifests"][1]]
        self.replace_root(tag, root)
        self.pack()
        with self.assertRaisesRegex(ValueError, "exactly one linux/arm64"):
            prepare.prepare(self.source, self.output)

    def test_reject_incorrect_descriptor_size(self):
        tag = next(iter(self.roots))
        root = json.loads(self.members[blob_path(self.roots[tag])])
        root["manifests"][0]["size"] += 1
        self.replace_root(tag, root)
        self.pack()
        with self.assertRaisesRegex(ValueError, "Blob size or checksum"):
            prepare.prepare(self.source, self.output)

    def test_reject_mismatched_docker_tag_record_and_duplicate_paths(self):
        original = self.docker[0]["Config"]
        self.docker[0]["Config"] = self.docker[1]["Config"]
        self.pack()
        with self.assertRaisesRegex(ValueError, "Inconsistent Docker-compatible"):
            prepare.prepare(self.source, self.output)
        self.docker[0]["Config"] = original
        self.pack(duplicate="index.json")
        with self.assertRaisesRegex(ValueError, "Duplicate archive paths"):
            prepare.prepare(self.source, self.output)

    def test_reuse_identical_output_and_preserve_conflicts(self):
        prepare.prepare(self.source, self.output)
        before = self.output.stat()
        prepare.prepare(self.source, self.output)
        self.assertEqual((self.output.stat().st_ino, self.output.stat().st_mtime_ns),
                         (before.st_ino, before.st_mtime_ns))
        conflicting = self.root / "conflicting.tar"
        conflicting.write_bytes(b"preserve existing artifact")
        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            prepare.prepare(self.source, conflicting)
        self.assertEqual(conflicting.read_bytes(), b"preserve existing artifact")
        self.assertFalse(list(self.root.glob(".*.part")))
        with self.assertRaisesRegex(ValueError, "different files"):
            prepare.prepare(self.source, self.source)


if __name__ == "__main__":
    unittest.main()
