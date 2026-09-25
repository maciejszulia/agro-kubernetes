"""Check resolved kernel requirements without Docker, downloads or compilation."""

from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build-kernel.sh"
BASE_BUILTINS = runpy.run_path(str(ROOT / "scripts/prepare-kernel.py"))["REQUIRED_BUILTINS"]
NETWORK_BUILTINS = """
IP_NF_TARGET_REJECT NETFILTER_XT_MATCH_MULTIPORT NETFILTER_XT_MATCH_STATISTIC
NETFILTER_XT_MATCH_IPVS IP_SET IP_SET_HASH_IP IP_SET_HASH_NET NETFILTER_XT_SET
NETFILTER_XT_MATCH_PHYSDEV NETFILTER_XT_MATCH_LIMIT NETFILTER_XT_TARGET_NFLOG
""".split()


class BuildKernelConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agro-build-config-")
        self.addCleanup(temporary.cleanup)
        self.config = Path(temporary.name) / ".config"
        self.options = {"CONFIG_" + name: "y" for name in BASE_BUILTINS + NETWORK_BUILTINS}
        self.options.update(CONFIG_HZ="100", CONFIG_LOCALVERSION='"-agro1"',
                            CONFIG_LOCALVERSION_AUTO="n")

    def check(self, options):
        self.config.write_text("".join(
            f"# {name} is not set\n" if value == "n" else f"{name}={value}\n"
            for name, value in options.items()
        ))
        return subprocess.run(["bash", str(SCRIPT), "--check-config", str(self.config)],
                              capture_output=True, text=True, timeout=10)

    def test_accept_required_builtins_and_release(self):
        result = self.check(self.options)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("configuration: PASS", result.stdout)

    def test_reject_each_missing_network_builtin(self):
        for name in NETWORK_BUILTINS:
            with self.subTest(option=name):
                options = dict(self.options)
                options["CONFIG_" + name] = "m"
                result = self.check(options)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("CONFIG_" + name, result.stderr)

    def test_retain_direct_boot_and_k3s_requirements(self):
        for name, value in (("HZ", "250"), ("HZ_100", "n"), ("VIRTIO_BLK", "m"),
                            ("DEVTMPFS_MOUNT", "n"), ("SERIAL_AMBA_PL011_CONSOLE", "n"),
                            ("OVERLAY_FS", "m"), ("MEMCG", "n")):
            with self.subTest(option=name):
                options = dict(self.options)
                options["CONFIG_" + name] = value
                result = self.check(options)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("CONFIG_" + name, result.stderr)

    def test_reject_wrong_or_automatic_release_suffix(self):
        for name, value in (("LOCALVERSION", '"-other"'), ("LOCALVERSION_AUTO", "y")):
            with self.subTest(option=name):
                options = dict(self.options)
                options["CONFIG_" + name] = value
                result = self.check(options)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("CONFIG_" + name, result.stderr)


if __name__ == "__main__":
    unittest.main()
