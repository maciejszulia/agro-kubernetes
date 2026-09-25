#!/data/data/com.termux/files/usr/bin/bash
set -eu
umask 077

source_dir=/sdcard/Android/data/com.termux/files/mobile-lab
exec > "$source_dir/access.log" 2>&1
state="$HOME/.local/state/mobile-lab"
mkdir -p "$state"
chmod 700 "$state"

if ! command -v sshd >/dev/null 2>&1; then
    apt-get update
    apt-get install -y openssh
fi

ssh-keygen -l -f "$source_dir/access_ed25519.pub" >/dev/null
install -m 600 "$source_dir/access_ed25519.pub" "$state/authorized_keys"
if [ ! -f "$state/ssh_host_ed25519_key" ]; then
    ssh-keygen -q -t ed25519 -N '' -f "$state/ssh_host_ed25519_key"
fi

cat > "$state/sshd_config" <<EOF
Port 8022
ListenAddress 127.0.0.1
HostKey $state/ssh_host_ed25519_key
PidFile $state/sshd.pid
AuthorizedKeysFile $state/authorized_keys
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PermitRootLogin no
Subsystem sftp internal-sftp
EOF

sshd -t -f "$state/sshd_config"
termux-wake-lock
is_lab_sshd_running() {
    python3 - "$state" <<'PY'
import pathlib, socket, sys
state = pathlib.Path(sys.argv[1])
try:
    pid = int((state / "sshd.pid").read_text())
    process = pathlib.Path(f"/proc/{pid}")
    command = (process / "cmdline").read_bytes()
    if "sshd" not in (process / "comm").read_text():
        raise ValueError("Unrelated PID")
    if str(state / "sshd_config").encode() not in command:
        raise ValueError("Different SSH configuration")
    with socket.create_connection(("127.0.0.1", 8022), timeout=2) as connection:
        if not connection.recv(255).startswith(b"SSH-2.0-"):
            raise ValueError("No SSH listener")
except (OSError, ValueError):
    sys.exit(1)
PY
}

if is_lab_sshd_running; then
    printf 'MOBILE_LAB_SSH_ALREADY_RUNNING\n'
else
    sshd -f "$state/sshd_config" -E "$state/sshd.log"
    is_lab_sshd_running
    printf 'MOBILE_LAB_SSH_READY\n'
fi
