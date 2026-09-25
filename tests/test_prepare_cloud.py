"""Exercise cloud preparation with temporary keys and a tiny local image fixture."""

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare-cloud.py"
SPEC = importlib.util.spec_from_file_location("prepare_cloud", SCRIPT)
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


class PrepareCloudTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agro-cloud-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "output"
        self.fixture = self.root / "source.qcow2"
        self.fixture.write_bytes(b"local image checksum fixture\n" * 16)
        constants = patch.multiple(
            prepare, URL=self.fixture.as_uri(),
            SHA512=hashlib.sha512(self.fixture.read_bytes()).hexdigest(),
        )
        constants.start()
        self.addCleanup(constants.stop)
        self.private = self.root / "client_key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "",
                        "-f", str(self.private)], check=True, capture_output=True, timeout=10)
        self.public = self.private.with_suffix(".pub")
        self.key = self.public.read_text().strip()

    def run_main(self, name="xa2-01", public=None):
        previous = sys.argv
        sys.argv = [str(SCRIPT), "--public-key", str(public or self.public),
                    "--output", str(self.output), "--name=" + name]
        try:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                prepare.main()
            return output.getvalue()
        finally:
            sys.argv = previous

    def test_reject_invalid_public_keys(self):
        for label, content in (
            ("empty", ""), ("wrong type", "ssh-rsa invalid\n"),
            ("malformed", "ssh-ed25519 not-base64\n"),
            ("multiline", self.key + "\n" + self.key + "\n"),
        ):
            with self.subTest(case=label):
                public = self.root / "invalid.pub"
                public.write_text(content)
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    self.run_main(public=public)
                self.assertFalse(self.output.exists())

    def test_reject_private_key_without_disclosing_it(self):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--public-key", str(self.private),
             "--output", str(self.output)], capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.private.read_text() not in result.stdout + result.stderr,
                        "Private key material must not appear in command output")
        self.assertFalse(self.output.exists())

    def test_reject_invalid_hostname(self):
        for name in ("", "-invalid", "invalid-", "../escape", "a" * 64, "bad\nname"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.run_main(name=name)
                self.assertFalse(self.output.exists())

    def test_cli_reports_sanitized_failure_cause(self):
        malformed = self.root / "malformed.pub"
        malformed.write_text("ssh-ed25519 not-base64\n")
        for public, name, expected in (
            (self.public, "bad/name", "lowercase DNS hostname"),
            (self.root / "missing.pub", "xa2-01", "No such file or directory"),
            (malformed, "xa2-01", "ssh-keygen exited with code"),
        ):
            with self.subTest(cause=expected):
                result = subprocess.run(
                    [sys.executable, "-B", str(SCRIPT), "--public-key", str(public),
                     "--output", str(self.output), "--name", name],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn(expected, result.stderr)
                self.assertNotIn("not-base64", result.stderr)
                self.assertFalse(self.output.exists())

    def test_preserve_invalid_existing_image(self):
        self.output.mkdir()
        image = self.output / prepare.IMAGE
        image.write_bytes(b"existing image to preserve")
        with self.assertRaises(ValueError):
            prepare.prepare_image(self.output)
        self.assertEqual(image.read_bytes(), b"existing image to preserve")
        self.assertFalse((self.output / (prepare.IMAGE + ".part")).exists())

    def test_reuse_verified_cache_without_source(self):
        self.output.mkdir()
        image = self.output / prepare.IMAGE
        image.write_bytes(self.fixture.read_bytes())
        self.fixture.unlink()
        before = image.stat()
        self.assertEqual(prepare.prepare_image(self.output), image)
        self.assertEqual(image.stat().st_ino, before.st_ino)
        self.assertEqual(image.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertTrue(prepare.verified(image))

    def test_reject_corrupt_download(self):
        self.output.mkdir()
        self.fixture.write_bytes(b"corrupt downloaded bytes")
        with self.assertRaises(ValueError):
            prepare.prepare_image(self.output)
        self.assertFalse((self.output / prepare.IMAGE).exists())
        self.assertEqual((self.output / (prepare.IMAGE + ".part")).read_bytes(),
                         b"corrupt downloaded bytes")

    def test_resume_partial_download(self):
        self.output.mkdir()
        partial = self.output / (prepare.IMAGE + ".part")
        partial.write_bytes(self.fixture.read_bytes()[:8])
        image = prepare.prepare_image(self.output)
        self.assertTrue(prepare.verified(image))
        self.assertFalse(partial.exists())

    def test_promote_verified_partial_without_source(self):
        self.output.mkdir()
        partial = self.output / (prepare.IMAGE + ".part")
        partial.write_bytes(self.fixture.read_bytes())
        self.fixture.unlink()
        image = prepare.prepare_image(self.output)
        self.assertTrue(prepare.verified(image))
        self.assertFalse(partial.exists())

    def test_create_cidata_with_only_expected_configuration(self):
        output = self.run_main(name="xa2-02")
        seed = self.output / "seed.iso"
        with seed.open("rb") as stream:
            stream.seek(16 * 2048)
            descriptor = stream.read(2048)
        self.assertEqual(descriptor[:7], b"\x01CD001\x01")
        self.assertEqual(descriptor[40:72].rstrip(b" "), b"CIDATA")
        names = subprocess.check_output(["bsdtar", "-tf", str(seed)], text=True).splitlines()
        self.assertEqual(set(names) - {"."}, {"meta-data", "user-data"})
        metadata = subprocess.check_output(["bsdtar", "-xOf", str(seed), "meta-data"], text=True)
        userdata = subprocess.check_output(["bsdtar", "-xOf", str(seed), "user-data"], text=True)
        self.assertEqual(metadata, "instance-id: agro-kubernetes-xa2-02-cloud-001\n"
                                  "hostname: xa2-02\n"
                                  "local-hostname: xa2-02\n")
        expected = ("#cloud-config\nuser:\n  name: alpine\n  shell: /bin/ash\n"
                    f"ssh_authorized_keys:\n  - {json.dumps(self.key)}\n")
        self.assertTrue(userdata == expected, "Seed must contain only the expected user/key configuration")
        self.assertTrue(self.key not in output, "Generated key material must not be printed")
        self.assertEqual(set(path.name for path in self.output.iterdir()), {prepare.IMAGE, "seed.iso"})


if __name__ == "__main__":
    unittest.main()
