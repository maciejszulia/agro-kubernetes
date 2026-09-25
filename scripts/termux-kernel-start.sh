#!/data/data/com.termux/files/usr/bin/bash
set -eu
umask 077

state="$HOME/mobile-lab/xa2-01-hz100"
cloud="$HOME/mobile-lab/xa2-01-cloud"
if [ "$#" -gt 1 ] || { [ "$#" -eq 1 ] && { [ -z "$1" ] || [[ $1 == -* ]]; }; }; then
    echo 'Usage: termux-kernel-start.sh [BUILT_KERNEL_DIRECTORY]' >&2
    exit 2
fi
kernel="$state/Image"
if [ "$#" -eq 1 ]; then
    kernel=$(python3 - "$1" <<'PY'
import hashlib, json, sys
from pathlib import Path

# Local consistency checks do not constitute a build or origin attestation.
try:
    directory = Path(sys.argv[1]).resolve(strict=True)
    image, config = directory / 'Image', directory / 'kernel.config'
    metadata = json.loads((directory / 'build-metadata.json').read_text())
    expected = {
        'release': '7.1.5-agro1',
        'source_sha256': '22a0196b3cbcdf34dc27b77561f4d040585fd3447edc9ab3531a1ac79e3041e7',
        'baseline_config_sha256': 'c8f5253a5ae005a3a6767fd732267b24e562548fd5440fb6bed3eccd8f572297',
    }
    if not isinstance(metadata, dict) or any(metadata.get(key) != value for key, value in expected.items()):
        raise ValueError('Unsupported kernel release, source or baseline')
    for path, key in ((image, 'image_sha256'), (config, 'resolved_config_sha256')):
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != metadata.get(key):
                raise ValueError('Artifact checksum mismatch: ' + path.name)
    with image.open('rb') as stream:
        stream.seek(0x38)
        if stream.read(4) != b'ARMd':
            raise ValueError('Missing ARM64 Image magic')
    options = dict(line.split('=', 1) for line in config.read_text().splitlines()
                   if line.startswith('CONFIG_') and '=' in line)
    builtins = '''HZ_100 VIRTIO VIRTIO_PCI VIRTIO_BLK VIRTIO_NET EXT4_FS DEVTMPFS DEVTMPFS_MOUNT
SERIAL_AMBA_PL011 SERIAL_AMBA_PL011_CONSOLE EFI_PARTITION CGROUPS MEMCG CGROUP_PIDS
NAMESPACES UTS_NS IPC_NS USER_NS PID_NS NET_NS OVERLAY_FS BRIDGE BRIDGE_NETFILTER
NETFILTER NF_CONNTRACK NF_NAT VXLAN VETH IP_NF_IPTABLES IP_NF_FILTER IP_NF_NAT
IP_NF_TARGET_MASQUERADE SECCOMP SECCOMP_FILTER ISO9660_FS IP_NF_TARGET_REJECT
NETFILTER_XT_MATCH_MULTIPORT NETFILTER_XT_MATCH_STATISTIC NETFILTER_XT_MATCH_IPVS IP_SET
IP_SET_HASH_IP IP_SET_HASH_NET NETFILTER_XT_SET NETFILTER_XT_MATCH_PHYSDEV
NETFILTER_XT_MATCH_LIMIT NETFILTER_XT_TARGET_NFLOG'''.split()
    required = {'CONFIG_' + name: 'y' for name in builtins}
    required.update(CONFIG_HZ='100', CONFIG_LOCALVERSION='"-agro1"')
    missing = [name for name, value in required.items() if options.get(name) != value]
    if missing or options.get('CONFIG_LOCALVERSION_AUTO', 'n') != 'n':
        raise ValueError('Kernel configuration requirements failed')
    print(image)
except (OSError, ValueError, TypeError) as error:
    raise SystemExit('Built-kernel validation failed: ' + str(error))
PY
)
else
    printf '%s  %s\n' c27d833649ea86473baedc24e8deb246c525a579c66f61b152d7505cc1a79969 "$kernel" | sha256sum -c -
fi
test -r "$cloud/seed.iso"
printf '%s  %s\n' \
    eb983aabed32fbf17ccca2ce5e0090d06d860caa52a93ed416d775f18b04d0d9a347366d0dae86ec2ae3923b6c728bb9ec1995fcb036dd63b467125e4b42a7dd \
    "$cloud/base.qcow2" | sha512sum -c -

if [ -f "$state/qemu.pid" ] && kill -0 "$(cat "$state/qemu.pid")" 2>/dev/null; then
    echo 'The kernel-comparison guest already has a live PID.' >&2
    exit 1
fi
cd "$state"
if [ ! -e root.qcow2 ]; then
    qemu-img create -f qcow2 -F qcow2 -b ../xa2-01-cloud/base.qcow2 root.qcow2
    qemu-img resize root.qcow2 4G
fi

termux-wake-lock
qemu-system-aarch64 \
    -name xa2-01-hz100 \
    -machine virt,gic-version=3 \
    -accel tcg,thread=multi,tb-size=128 \
    -cpu max,pauth-impdef=on -smp 2 -m 768 \
    -kernel "$kernel" \
    -append 'root=/dev/vda2 rootfstype=ext4 rw rootwait console=ttyAMA0,115200' \
    -drive "if=none,id=rootdisk,format=qcow2,file=$state/root.qcow2" \
    -device virtio-blk-pci,drive=rootdisk,serial=agro-kubernetes-xa201 \
    -drive "if=virtio,format=raw,readonly=on,file=$cloud/seed.iso" \
    -netdev user,id=net0,ipv6=off,hostfwd=tcp:127.0.0.1:10022-:22,hostfwd=tcp:127.0.0.1:10080-:30080 \
    -device virtio-net-pci,netdev=net0 \
    -device virtio-rng-pci \
    -display none \
    -chardev "socket,id=console,host=127.0.0.1,port=10023,server=on,wait=off,logfile=$state/console.log,logappend=on" \
    -serial chardev:console \
    -monitor "unix:$state/monitor.sock,server=on,wait=off" \
    -pidfile "$state/qemu.pid" -daemonize
printf 'Kernel-comparison guest PID %s; runtime verification is required.\n' "$(cat "$state/qemu.pid")"
