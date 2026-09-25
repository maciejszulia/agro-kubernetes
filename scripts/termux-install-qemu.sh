#!/data/data/com.termux/files/usr/bin/bash
set -eu
umask 077
state="$HOME/.local/state/mobile-lab"
mkdir -p "$state"
rm -f "$state/install-qemu.exit"
exec > "$state/install-qemu.log" 2>&1
trap 'result=$?; printf "%s\n" "$result" > "$state/install-qemu.exit"' EXIT

date -Iseconds
printf 'deb https://packages.termux.dev/apt/termux-main stable main\n' > "$state/termux-main.list"
set -- -o "Dir::Etc::sourcelist=$state/termux-main.list" -o 'Dir::Etc::sourceparts=-'
apt-get "$@" -o APT::Update::Error-Mode=any update
apt-get "$@" install -y --no-install-recommends qemu-system-aarch64-headless qemu-utils
qemu-system-aarch64 --version
qemu-img --version
test -r "$PREFIX/share/qemu/edk2-aarch64-code.fd"
dpkg-query -W -f='${Package} ${Version}\n' qemu-system-aarch64-headless qemu-utils qemu-common
