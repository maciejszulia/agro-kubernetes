#!/bin/sh
set -eu
umask 077

# This installer may write only the new disk presented by this lab's QEMU process.
test "$(id -u)" = 0
test "$(uname -m)" = aarch64
case "$(uname -r)" in *-virt) ;; *) echo 'Expected Alpine virt kernel' >&2; exit 1 ;; esac
test -d /sys/firmware/efi
test "$(cat /sys/block/vda/serial)" = mobile-lab-xa2-01
test "$(cat /sys/block/vda/size)" = 8388608
for partition in /sys/block/vda/vda*; do
    if [ -e "$partition" ]; then
        echo 'Refusing installation onto an already partitioned guest disk' >&2
        exit 1
    fi
done
if grep -q '^/dev/vda' /proc/mounts; then
    echo 'Refusing installation onto a mounted guest disk' >&2
    exit 1
fi
header=$(mktemp)
trap 'rm -f "$header"' EXIT
dd if=/dev/vda of="$header" bs=1048576 count=1 2>/dev/null
test "$(wc -c < "$header")" -eq 1048576
if [ -n "$(od -An -tx1 "$header" | tr -d '0[:space:]*')" ]; then
    echo 'Refusing installation: the guest disk header is not blank' >&2
    exit 1
fi
test -r /root/owner.pub
ip link show eth0 >/dev/null

cat > /root/lab-answers <<'EOF'
KEYMAPOPTS=none
HOSTNAMEOPTS=xa2-01
DEVDOPTS=mdev
INTERFACESOPTS="auto lo
iface lo inet loopback

auto eth0
iface eth0 inet dhcp
"
TIMEZONEOPTS=UTC
PROXYOPTS=none
APKREPOSOPTS="-1"
USEROPTS=none
SSHDOPTS=openssh
ROOTSSHKEY="$(cat /root/owner.pub)"
NTPOPTS=none
DISKOPTS=none
LBUOPTS=none
APKCACHEOPTS=none
EOF

setup-alpine -e -f /root/lab-answers </dev/null
cat > /etc/ssh/sshd_config <<'EOF'
PermitRootLogin prohibit-password
PubkeyAuthentication yes
AuthenticationMethods publickey
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
Subsystem sftp internal-sftp
EOF
sshd -t
rc-service sshd restart
ERASE_DISKS=/dev/vda KERNELOPTS='console=ttyAMA0,115200' \
    setup-disk -m sys -s 0 -k virt /dev/vda </dev/null
printf 'MOBILE_LAB_GUEST_INSTALLED\n'
