#!/data/data/com.termux/files/usr/bin/bash
set -eu
umask 077

state="$HOME/mobile-lab/xa2-01-cloud"
firmware="$PREFIX/share/qemu/edk2-aarch64-code.fd"
test -r "$firmware"
test -r "$state/seed.iso"
printf '%s  %s\n' \
    eb983aabed32fbf17ccca2ce5e0090d06d860caa52a93ed416d775f18b04d0d9a347366d0dae86ec2ae3923b6c728bb9ec1995fcb036dd63b467125e4b42a7dd \
    "$state/base.qcow2" | sha512sum -c -

if [ -f "$state/qemu.pid" ] && kill -0 "$(cat "$state/qemu.pid")" 2>/dev/null; then
    echo 'The cloud guest already has a live PID; inspect it before another start.' >&2
    exit 1
fi

cd "$state"
chmod 400 base.qcow2
if [ ! -e root.qcow2 ]; then
    qemu-img create -f qcow2 -F qcow2 -b base.qcow2 root.qcow2
    qemu-img resize root.qcow2 4G
fi

termux-wake-lock
qemu-system-aarch64 \
    -name xa2-01-cloud \
    -machine virt,gic-version=3 \
    -accel tcg,thread=multi,tb-size=256 \
    -cpu max,pauth-impdef=on -smp 2 -m 1024 \
    -bios "$firmware" \
    -drive "if=none,id=rootdisk,format=qcow2,file=$state/root.qcow2" \
    -device virtio-blk-pci,drive=rootdisk,serial=agro-kubernetes-xa201 \
    -drive "if=virtio,format=raw,readonly=on,file=$state/seed.iso" \
    -netdev user,id=net0,ipv6=off,hostfwd=tcp:127.0.0.1:10022-:22,hostfwd=tcp:127.0.0.1:16443-:6443,hostfwd=tcp:127.0.0.1:10080-:30080 \
    -device virtio-net-pci,netdev=net0 \
    -device virtio-rng-pci \
    -display none \
    -chardev "socket,id=console,host=127.0.0.1,port=10023,server=on,wait=off,logfile=$state/console.log,logappend=on" \
    -serial chardev:console \
    -monitor "unix:$state/monitor.sock,server=on,wait=off" \
    -pidfile "$state/qemu.pid" -daemonize
printf 'Cloud guest PID %s; verify SSH and the guest before claiming readiness.\n' "$(cat "$state/qemu.pid")"
