#!/data/data/com.termux/files/usr/bin/bash
set -eu
umask 077

state="$HOME/mobile-lab/xa2-01"
iso="$state/alpine-virt-3.24.2-aarch64.iso"
disk="$state/root.qcow2"
firmware="$PREFIX/share/qemu/edk2-aarch64-code.fd"
mode=${1:-disk}

case "$mode" in
    install|disk) ;;
    *) printf 'Usage: %s [install|disk]\n' "$0" >&2; exit 2 ;;
esac

mkdir -p "$state"
test -r "$firmware"
if [ -f "$state/qemu.pid" ] && kill -0 "$(cat "$state/qemu.pid")" 2>/dev/null; then
    printf 'The lab guest already has a running PID; inspect it before another start.\n' >&2
    exit 1
fi

if [ "$mode" = install ]; then
    test -r "$iso"
    printf '%s  %s\n' a57ba668b5f6b17a670fcf8e799d5d7fe43766ed086d6ce2927b0625bf43dbf6 "$iso" | sha256sum -c -
    if [ ! -e "$disk" ]; then
        qemu-img create -f qcow2 "$disk" 4G
    fi
    qemu-img map --output=json "$disk" > "$state/install-disk-map.json"
    python3 - "$state/install-disk-map.json" <<'PY'
import json, sys
with open(sys.argv[1]) as stream:
    extents = json.load(stream)
if not extents or any(part.get("data") or not part.get("zero") for part in extents):
    raise SystemExit("Refusing installation boot: the guest disk already contains data.")
PY
else
    test -f "$disk"
fi

set -- \
    -name xa2-01 \
    -machine virt -accel tcg,thread=single -cpu max \
    -smp 1 -m 1024 \
    -bios "$firmware" \
    -drive "if=none,id=rootdisk,format=qcow2,file=$disk" \
    -device virtio-blk-pci,drive=rootdisk,serial=mobile-lab-xa2-01 \
    -netdev user,id=net0,ipv6=off,hostfwd=tcp:127.0.0.1:10022-:22,hostfwd=tcp:127.0.0.1:16443-:6443,hostfwd=tcp:127.0.0.1:10080-:30080 \
    -device virtio-net-pci,netdev=net0 \
    -device virtio-rng-pci \
    -display none \
    -chardev "socket,id=console,host=127.0.0.1,port=10023,server=on,wait=off,logfile=$state/console.log,logappend=on" \
    -serial chardev:console \
    -monitor "unix:$state/monitor.sock,server=on,wait=off" \
    -pidfile "$state/qemu.pid" -daemonize

if [ "$mode" = install ]; then
    set -- "$@" \
        -device virtio-scsi-pci,id=scsi0 \
        -drive "if=none,id=cd0,format=raw,readonly=on,file=$iso" \
        -device scsi-cd,drive=cd0
fi

termux-wake-lock
qemu-system-aarch64 "$@"
printf 'Guest start requested; PID %s. Verify the console and workload before claiming readiness.\n' "$(cat "$state/qemu.pid")"
