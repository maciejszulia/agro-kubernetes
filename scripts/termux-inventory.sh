#!/data/data/com.termux/files/usr/bin/bash
set -eu

out=/sdcard/Android/data/com.termux/files/mobile-lab/inventory.txt
mkdir -p "$(dirname "$out")"
{
    date -Iseconds
    id
    uname -r -m
    printf '\nMemory\n'
    head -n 3 /proc/meminfo
    printf '\nPrivate storage\n'
    df -k "$HOME"
    printf '\nRequired tools\n'
    for tool in sshd ssh-keygen qemu-system-aarch64 qemu-img sv runsvdir curl wget; do
        command -v "$tool" || true
    done
    printf '\nRelevant packages\n'
    dpkg-query -W -f='${Package} ${Version}\n' | awk '/^(openssh|qemu|termux-services|runit|curl|wget|busybox|proot|tmux)/'
    printf '\nExisting boot script names\n'
    if [ -d "$HOME/.termux/boot" ]; then
        ls -1 "$HOME/.termux/boot"
    fi
    printf '\nService directory names\n'
    if [ -d "$PREFIX/var/service" ]; then
        ls -1 "$PREFIX/var/service"
    fi
} > "$out" 2>&1
printf 'MOBILE_LAB_INVENTORY_READY\n'
