"""Exercise native-control setup with temporary paths and inert command stubs."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/termux-native-control.sh"
native = types.ModuleType("native_control_test")
exec(compile(SCRIPT.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0],
             str(SCRIPT), "exec"), native.__dict__)
WAIT_SUPERVISOR = native.wait_supervisor


class NativeControlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agro-native-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.prefix = self.root / "prefix"
        self.state = self.home / "mobile-lab/native-control"
        (self.state / "bin").mkdir(parents=True)
        self.state.chmod(0o700)
        self.binary = self.state / "bin/k3s"
        self.binary.write_bytes(b"synthetic pinned launcher")
        self.binary.chmod(0o700)
        (self.prefix / "bin").mkdir(parents=True)
        (self.prefix / "etc").mkdir()
        (self.prefix / "etc/resolv.conf").write_text("nameserver 192.0.2.53\n")
        (self.prefix / "var/service").mkdir(parents=True)
        self.service = self.prefix / "var/service/agro-k3s-control"
        for name in ("sh", "proot", "sv", "svlogd", "termux-wake-lock"):
            tool = self.prefix / "bin" / name
            tool.write_text("#!/bin/sh\nexit 99\n")
            tool.chmod(0o700)
        self.commands = []
        for patched in (
            patch.object(Path, "home", return_value=self.home),
            patch.dict(os.environ, PREFIX=str(self.prefix)),
            patch.object(native, "K3S_SHA256", hashlib.sha256(self.binary.read_bytes()).hexdigest()),
            patch.object(native.subprocess, "run", side_effect=self.run_command),
            patch.object(native, "wait_supervisor", side_effect=self.supervise),
        ):
            patched.start()
            self.addCleanup(patched.stop)

    def run_command(self, command, **kwargs):
        self.commands.append((command, kwargs))
        if Path(command[0]).name == "proot":
            server = self.state / "data/data/current/bin/k3s-server"
            server.parent.mkdir(parents=True, exist_ok=True)
            server.write_text("#!/bin/sh\nexit 99\n")
            server.chmod(0o700)
        return subprocess.CompletedProcess(command, 0, stdout=b"{}", stderr=b"")

    def supervise(self, service):
        for relative in ("supervise/ok", "log/supervise/ok"):
            fifo = service / relative
            fifo.parent.mkdir(exist_ok=True)
            if not fifo.exists():
                os.mkfifo(fifo)
        WAIT_SUPERVISOR(service)

    def setup_control(self, ip="192.168.1.50"):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            native.main(["--node-ip", ip])
        return output.getvalue()

    def test_valid_setup_and_repeat_preserve_private_state(self):
        output = self.setup_control()
        settings = json.loads((self.state / "config.yaml").read_text())
        self.assertTrue(settings["rootless"] and settings["disable-agent"])
        self.assertEqual(settings["node-ip"], "192.168.1.50")
        self.assertEqual(settings["bind-address"], "127.0.0.1")
        self.assertEqual(settings["https-listen-port"], 16443)
        self.assertEqual(settings["advertise-address"], "10.0.2.2")
        self.assertEqual(settings["tls-san"], ["127.0.0.1", "10.0.2.2"])
        self.assertEqual(settings["egress-selector-mode"], "cluster")
        self.assertEqual(settings["write-kubeconfig-mode"], "0600")
        self.assertNotIn("token", settings)
        self.assertEqual((self.state / "log/config").read_text(), "s1048576\nn3\n")
        self.assertEqual((self.state / "config.yaml").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.service / "run").stat().st_mode & 0o777, 0o700)
        command, options = self.commands[0]
        self.assertEqual(command[1:], ["-r", "/", "-w", str(self.state), str(self.binary),
                                       "kubectl", "version", "--client", "-o", "json"])
        self.assertEqual(options["env"]["GOMAXPROCS"], "2")
        run = (self.service / "run").read_text()
        self.assertIn("k3s-server server --config", run)
        self.assertNotIn("PROOT_NO_SECCOMP", run)
        secret = self.state / "data/synthetic-token"
        secret.write_text("retain synthetic secret")
        paths = [secret, self.state / "config.yaml", self.service / "run", self.state / "log/config"]
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
        output += self.setup_control()
        self.assertEqual({path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}, before)
        self.assertNotIn("retain synthetic secret", output)
        self.assertIn("readiness require separate checks", output)

    def test_invalid_ips_fail_before_commands_or_configuration(self):
        for ip in ("", "127.0.0.1", "0.0.0.0", "224.0.0.1", "::1", "1.2.3", "bad"):
            with self.subTest(ip=ip), self.assertRaises(ValueError):
                self.setup_control(ip)
        self.assertEqual(self.commands, [])
        self.assertFalse((self.state / "config.yaml").exists())
        self.assertFalse(self.service.exists())

    def test_missing_argument_and_corrupt_binary_fail_before_changes(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            native.main([])
        self.binary.write_bytes(b"wrong launcher")
        with self.assertRaises(ValueError):
            self.setup_control()
        self.assertEqual(self.commands, [])
        self.assertFalse((self.state / "config.yaml").exists())

    def test_conflicting_config_or_service_is_not_adopted(self):
        config = self.state / "config.yaml"
        config.write_text("unrelated configuration")
        with self.assertRaises(ValueError):
            self.setup_control()
        self.assertEqual(config.read_text(), "unrelated configuration")
        config.unlink()
        self.service.mkdir()
        (self.service / "run").write_text("unrelated service")
        with self.assertRaises(ValueError):
            self.setup_control()
        self.assertEqual((self.service / "run").read_text(), "unrelated service")
        self.assertEqual(self.commands, [])

    def test_runtime_symlink_and_disabled_service_are_preserved(self):
        foreign = self.root / "foreign"
        foreign.mkdir()
        (self.state / "data").symlink_to(foreign, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.setup_control()
        self.assertEqual(list(foreign.iterdir()), [])
        self.assertEqual(self.commands, [])
        (self.state / "data").unlink()
        self.setup_control()
        (self.service / "down").touch()
        self.commands.clear()
        with self.assertRaises(ValueError):
            self.setup_control()
        self.assertTrue((self.service / "down").exists())
        self.assertEqual(self.commands, [])

    def test_supervisor_wait_is_bounded(self):
        with patch.object(native.time, "monotonic", side_effect=[0, 16]), self.assertRaises(RuntimeError):
            WAIT_SUPERVISOR(self.service)

    def test_missing_resolver_and_nonexecutable_service_fail_before_bootstrap(self):
        resolver = self.prefix / "etc/resolv.conf"
        resolver.unlink()
        with self.assertRaises(ValueError):
            self.setup_control()
        self.assertEqual(self.commands, [])
        self.assertFalse((self.state / "config.yaml").exists())
        resolver.write_text("nameserver 192.0.2.53\n")
        self.setup_control()
        self.commands.clear()
        (self.service / "run").chmod(0o600)
        with self.assertRaises(ValueError):
            self.setup_control()
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main()
