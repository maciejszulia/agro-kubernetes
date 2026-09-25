"""Verify the K3s download boundary with a tiny local fixture."""

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare-k3s.py"
SPEC = importlib.util.spec_from_file_location("prepare_k3s", SCRIPT)
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


class PrepareK3sTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agro-k3s-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.write_bytes(b"local K3s artifact fixture\n")
        self.output = self.root / "output"
        constants = patch.multiple(prepare, URL=self.source.as_uri(),
                                  SHA256=hashlib.sha256(self.source.read_bytes()).hexdigest())
        constants.start()
        self.addCleanup(constants.stop)

    def test_download_only_verified_executable_and_resume(self):
        self.output.mkdir()
        partial = self.output / (prepare.BINARY + ".part")
        partial.write_bytes(self.source.read_bytes()[:4])
        binary = prepare.prepare(self.output)
        self.assertEqual(binary.read_bytes(), self.source.read_bytes())
        self.assertEqual(binary.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(self.output.iterdir()), [binary])

    def test_reuse_cache_and_verified_partial_without_download(self):
        contents = self.source.read_bytes()
        self.source.unlink()
        for suffix in ("", ".part"):
            with self.subTest(cached_suffix=suffix):
                output = self.root / ("cached" + suffix)
                output.mkdir()
                (output / (prepare.BINARY + suffix)).write_bytes(contents)
                binary = prepare.prepare(output)
                self.assertEqual(binary.read_bytes(), contents)
                before = binary.stat().st_mtime_ns
                self.assertEqual(prepare.prepare(output), binary)
                self.assertEqual(binary.stat().st_mtime_ns, before)

    def test_preserve_conflicting_existing_binary(self):
        self.output.mkdir()
        binary = self.output / prepare.BINARY
        binary.write_bytes(b"preserve unrelated binary")
        with self.assertRaises(ValueError):
            prepare.prepare(self.output)
        self.assertEqual(binary.read_bytes(), b"preserve unrelated binary")
        self.assertEqual(list(self.output.iterdir()), [binary])

    def test_reject_corrupt_download(self):
        self.source.write_bytes(b"corrupt download")
        with self.assertRaises(ValueError):
            prepare.prepare(self.output)
        self.assertFalse((self.output / prepare.BINARY).exists())


if __name__ == "__main__":
    unittest.main()
