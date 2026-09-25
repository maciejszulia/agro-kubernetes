#!/usr/bin/env bash
set -euo pipefail
umask 077

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
version=7.1.5
archive="linux-$version.tar.xz"
source_url="https://cdn.kernel.org/pub/linux/kernel/v7.x/$archive"
source_sha=22a0196b3cbcdf34dc27b77561f4d040585fd3447edc9ab3531a1ac79e3041e7
baseline_sha=c8f5253a5ae005a3a6767fd732267b24e562548fd5440fb6bed3eccd8f572297
builder=agro-kubernetes-kernel-builder:bookworm
fragment="$repo/config/k3s-kernel.config"

die() { printf '%s\n' "$*" >&2; exit 1; }
check_config() {
    python3 -B - "$repo" "$1" <<'PY'
from pathlib import Path
import re, runpy, sys
repo, config = Path(sys.argv[1]), Path(sys.argv[2])
def options(path):
    result = {}
    for line in path.read_text().splitlines():
        if line.startswith('CONFIG_') and '=' in line:
            key, value = line.split('=', 1)
            result[key] = value
        elif match := re.fullmatch(r'# (CONFIG_[A-Z0-9_]+) is not set', line):
            result[match[1]] = 'n'
    return result
base = runpy.run_path(str(repo / 'scripts/prepare-kernel.py'))['REQUIRED_BUILTINS']
required = {'CONFIG_' + key: 'y' for key in base}
required['CONFIG_HZ'] = '100'
required.update(options(repo / 'config/k3s-kernel.config'))
actual = options(config)
missing = [key for key, value in required.items() if actual.get(key) != value]
if missing:
    raise SystemExit('Resolved kernel configuration failed: ' + ', '.join(missing))
print('Resolved kernel configuration: PASS')
PY
}

if [[ ${1:-} == --check-config ]]; then
    [[ $# == 2 ]] || die 'Usage: build-kernel.sh --check-config FILE'
    check_config "$2"
    exit
fi
output=
baseline="${XDG_CACHE_HOME:-$HOME/.cache}/mobile-lab/podroid-v1.2.9/kernel.config"
while (($#)); do
    case "$1" in
        --output|--baseline)
            [[ $# -ge 2 && -n $2 ]] || die "Missing value for $1"
            if [[ $1 == --output ]]; then output=$2; else baseline=$2; fi
            shift 2 ;;
        --help|-h) printf 'Usage: bash scripts/build-kernel.sh --output DIRECTORY [--baseline FILE]\n'; exit ;;
        *) die "Unknown argument: $1" ;;
    esac
done
[[ -n $output ]] || die '--output is required'
baseline=$(realpath -e -- "$baseline")
output=$(realpath -m -- "$output")
for path in "$repo" "$baseline" "$output"; do
    [[ $path != *','* && $path != *$'\n'* ]] || die 'Mount paths must not contain commas or newlines'
done
printf '%s  %s\n' "$baseline_sha" "$baseline" | sha256sum -c -
builder_id=$(docker image inspect --format '{{.Id}}' "$builder")
fragment_sha=$(sha256sum "$fragment" | cut -d' ' -f1)
identity="$version $source_sha $baseline_sha $fragment_sha $builder_id"
mkdir -p -- "$output"
if [[ -f $output/.build-inputs ]]; then
    [[ $(cat "$output/.build-inputs") == "$identity" ]] || die 'Build inputs changed; use a new output directory'
else
    while IFS= read -r -d '' path; do
        case ${path##*/} in
            "$archive"|"$archive.part") ;;
            *) die "Refusing unrelated existing output: $path" ;;
        esac
    done < <(find "$output" -mindepth 1 -maxdepth 1 -print0)
    (set -o noclobber; printf '%s\n' "$identity" > "$output/.build-inputs")
fi
mkdir "$output/.build-lock" 2>/dev/null || die 'Build already active or interrupted lock exists; inspect it first'
trap 'rmdir -- "$output/.build-lock"' EXIT
if [[ ! -e $output/$archive ]]; then
    partial="$output/$archive.part"
    if [[ ! -f $partial ]] || ! printf '%s  %s\n' "$source_sha" "$partial" | sha256sum -c - >/dev/null 2>&1; then
        curl --fail --location --retry 3 --retry-delay 2 --retry-max-time 600 \
            --connect-timeout 15 --max-time 300 --continue-at - --output "$partial" "$source_url"
    fi
    printf '%s  %s\n' "$source_sha" "$partial" | sha256sum -c -
    ln -- "$partial" "$output/$archive"
    rm -- "$partial"
fi
printf '%s  %s\n' "$source_sha" "$output/$archive" | sha256sum -c -
if [[ ! -d $output/source ]]; then
    mkdir "$output/source"
    tar -xJf "$output/$archive" --strip-components=1 -C "$output/source"
    touch "$output/source/.extracted"
fi
[[ -f $output/source/.extracted ]] || die 'Source extraction is incomplete; preserve it and use a new output directory'
mkdir -p "$output/work/tmp"
docker run --rm -i --user "$(id -u):$(id -g)" --cpus 3 --memory 4g \
    --network none --cap-drop ALL --security-opt no-new-privileges --read-only \
    --env TMPDIR=/build/tmp \
    --mount "type=bind,src=$output/work,dst=/build" \
    --mount "type=bind,src=$output/source,dst=/source,readonly" \
    --mount "type=bind,src=$baseline,dst=/inputs/baseline.config,readonly" \
    --mount "type=bind,src=$repo,dst=/repo,readonly" \
    --workdir /build "$builder_id" bash -se <<'BUILD'
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
if [[ ! -f /build/.configured ]]; then
    cp /inputs/baseline.config /build/.config
    /source/scripts/kconfig/merge_config.sh -m -O /build /build/.config /repo/config/k3s-kernel.config
    make -C /source O=/build olddefconfig
    bash /repo/scripts/build-kernel.sh --check-config /build/.config
    touch /build/.configured
fi
bash /repo/scripts/build-kernel.sh --check-config /build/.config
make -C /source O=/build -j3 Image
make -s -C /source O=/build kernelrelease > /build/kernel.release
python3 -B - <<'PY'
import json, subprocess
from pathlib import Path
def read(*command):
    return subprocess.check_output(command, text=True).strip()
record = {'cross_compiler': read('aarch64-linux-gnu-gcc', '--version'),
          'host_compiler': read('gcc', '--version'),
          'binutils': read('aarch64-linux-gnu-ld', '--version'),
          'packages': read('dpkg-query', '-W', '-f=${Package}=${Version}\n').splitlines()}
Path('/build/toolchain.json').write_text(json.dumps(record, indent=2) + '\n')
PY
BUILD
python3 -B - "$output" "$repo" "$baseline" "$source_url" "$builder_id" <<'PY'
import hashlib, json, os, shutil, sys, tempfile
from pathlib import Path
output, repo, baseline = map(Path, sys.argv[1:4])
source_url, builder_id = sys.argv[4:6]
work = output / 'work'
def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
image = work / 'arch/arm64/boot/Image'
with image.open('rb') as stream:
    stream.seek(0x38)
    if stream.read(4) != b'ARMd':
        raise SystemExit('Built image has no ARM64 Image magic')
release = (work / 'kernel.release').read_text().strip()
if release != '7.1.5-agro1':
    raise SystemExit('Unexpected kernel release: ' + release)
record = {'release': release, 'source_url': source_url,
          'source_sha256': sha(output / 'linux-7.1.5.tar.xz'),
          'baseline_config_sha256': sha(baseline),
          'fragment_sha256': sha(repo / 'config/k3s-kernel.config'),
          'resolved_config_sha256': sha(work / '.config'), 'image_sha256': sha(image),
          'builder_image_id': builder_id,
          'builder_dockerfile_sha256': sha(repo / 'docker/kernel-builder.Dockerfile'),
          'toolchain': json.loads((work / 'toolchain.json').read_text()),
          'reproducible_build_verified': False, 'attestation_verified': False}
metadata = work / 'build-metadata.json'
metadata.write_text(json.dumps(record, indent=2) + '\n')
files = {'Image': image, 'kernel.config': work / '.config', 'System.map': work / 'System.map',
         'build-metadata.json': metadata}
files.update({path.name: path for path in work.glob('modules.builtin*') if path.is_file()})
for name, source in files.items():
    destination = output / name
    if destination.exists() and sha(destination) != sha(source):
        raise SystemExit('Refusing to overwrite existing artifact: ' + str(destination))
with tempfile.TemporaryDirectory(prefix='.publish-', dir=output) as directory:
    for name, source in files.items():
        destination = output / name
        if not destination.exists():
            staged = Path(directory) / name
            shutil.copyfile(source, staged)
            os.link(staged, destination)
        print('Verified artifact:', destination)
PY
