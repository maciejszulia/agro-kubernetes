# First-phone runbook

This runbook covers the first Xperia's management connection, cloud image preparation and current
kernel launcher. A usable guest and recovery from ADB transport loss have been verified.
K3s remains blocked by missing kernel options. Several guest changes are manual; this is not an
end-to-end provisioning script. See the [verification record](verification.md).

## Prerequisites

- An identified Sony Xperia H3113 with authorized USB debugging and Termux installed.
- A management host with ADB, OpenSSH, Bash, Python 3.11 or newer, `curl` and `bsdtar`.
- A dedicated Ed25519 key and separate Termux/guest known-hosts files outside the repository.
- Termux OpenSSH, Python 3, QEMU and `qemu-img`.
- App-private storage for the cloud base, a growing 4 GiB overlay, seed, kernel and logs.

The optional replacement-kernel build also requires access to a Docker daemon and host capacity
for a compilation container limited to three CPUs and 4 GiB RAM.

The tested phone uses Android 9 / 50.2.A.3.77 and Termux 0.118.3. Its bootloader remains locked.
Android root, flashing and real phone partition changes are not part of this setup. The first-phone
wrappers have fixed users and ports; a second device requires independent configuration.

## Management access

1. Identify the phone through ADB and bind operations to its serial. Keep that identifier outside Git.
2. Create a dedicated key named `access_ed25519` under
   `${XDG_STATE_HOME:-$HOME/.local/state}/mobile-lab/xa2-01` on the management host.
3. Stage only its public key as `access_ed25519.pub`, plus `termux-inventory.sh` and
   `termux-access.sh`, under `/sdcard/Android/data/com.termux/files/mobile-lab` on the phone.
4. Run the inventory and access scripts with Bash inside Termux. They write `inventory.txt` and
   `access.log` in that staging directory.
5. Forward host TCP 18022 to phone TCP 8022 through the identified ADB device. Verify the SSH
   host-key fingerprint and save the accepted entry in the host state's `known_hosts` file.
6. Use `scripts/xa2-ssh id` to verify the Termux connection.

The access script keeps its SSH configuration, authorized key, host key, PID and log under
Termux's `$HOME/.local/state/mobile-lab`. It binds `127.0.0.1:8022` and disables password and
keyboard-interactive authentication. Port 8022 must be available to this dedicated listener.
The wrapper connects as `u0_a179` with strict host-key checking and the dedicated client key.

Run `termux-install-qemu.sh` with Bash inside Termux to install
`qemu-system-aarch64-headless` and `qemu-utils`. It uses an operation-specific official package
source without replacing existing sources. Read `install-qemu.exit` and `install-qemu.log` under
`$HOME/.local/state/mobile-lab`; a missing completion file does not prove success. QEMU and
qemu-img 11.0.3 were verified.

## Prepare the cloud image and kernel

Run from the repository root on the management host, after creating the dedicated key:

```sh
lab_state="${XDG_STATE_HOME:-$HOME/.local/state}/mobile-lab/xa2-01"
python3 scripts/prepare-cloud.py --public-key "$lab_state/access_ed25519.pub" --output "$lab_state/cloud" --name xa2-01
python3 scripts/prepare-kernel.py --output "$lab_state/kernel"
```

The cloud preparer downloads or reuses the checksum-pinned
`generic_alpine-3.24.1-aarch64-uefi-tiny-r0.qcow2` from the
[official Alpine cloud releases](https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/cloud/).
It validates the public key and creates `seed.iso` with the `CIDATA` volume label. The seed contains
only the hostname, `alpine` account configuration and public key; it does not configure K3s,
cgroups, `mdevd` or filesystem growth. A repeat invocation replaces the seed with the supplied
configuration while retaining a verified base image.

The kernel preparer downloads the pinned [Podroid v1.2.9 release](https://github.com/ExTV/Podroid/releases/tag/v1.2.9)
as an archive, verifies its hash and extracts only the kernel payload. It writes `Image`,
`kernel.config` and `verification.json`. The APK is not installed or executed. The preparer checks
selected embedded kernel options and refuses conflicting existing outputs; its feature checks
are narrower than K3s `check-config`.

These commands prepare local artifacts. Transfer into Termux and guest configuration remain
separate operations.

## Build the replacement kernel

The source build addresses the current K3s kernel configuration gap. As of 2026-09-25, compilation
is in progress; final artifacts, guest boot and runtime compatibility are not yet verified.

From the repository root, after extracting the baseline configuration above:

```sh
lab_state="${XDG_STATE_HOME:-$HOME/.local/state}/mobile-lab/xa2-01"
docker build --file docker/kernel-builder.Dockerfile --tag agro-kubernetes-kernel-builder:bookworm docker
bash scripts/build-kernel.sh --baseline "$lab_state/kernel/kernel.config" --output "$lab_state/kernel-build"
```

Pass `--baseline` explicitly: this runbook prepares the configuration under `$lab_state/kernel`,
while the script's default points to a different cache location.

| Build input | Pin |
|---|---|
| Linux source | `7.1.5`, SHA-256 `22a0196b3cbcdf34dc27b77561f4d040585fd3447edc9ab3531a1ac79e3041e7` |
| Extracted baseline configuration | SHA-256 `c8f5253a5ae005a3a6767fd732267b24e562548fd5440fb6bed3eccd8f572297` |
| Configuration fragment | [config/k3s-kernel.config](../config/k3s-kernel.config): eleven built-in network options and the `-agro1` release suffix |

Builder-image creation and source download use the network. Compilation runs in a container with
networking disabled, three CPUs and a 4 GiB memory limit. The script merges the fragment, resolves
dependencies with `olddefconfig` and validates the resulting configuration before building `Image`.

On success, the script verifies ARM64 Image format and release `7.1.5-agro1`, then writes `Image`,
`kernel.config`, `System.map`, `build-metadata.json` and any generated `modules.builtin*` files under
the output directory. Metadata records source/configuration/artifact hashes, builder identity and
toolchain versions. Bitwise reproducibility and upstream attestation remain unverified.

The output directory records its build inputs and rejects reuse with changed inputs or unrelated
files. Preserve an interrupted build for inspection rather than deleting its lock blindly.
The launcher has a separate input for completed build artifacts, described below. The build and
replacement-kernel boot remain unverified.

## Stage and boot the guest

Create the two target directories inside Termux app-private storage and transfer these artifacts:

| Prepared host artifact | Phone destination |
|---|---|
| `cloud/generic_alpine-3.24.1-aarch64-uefi-tiny-r0.qcow2` | `$HOME/mobile-lab/xa2-01-cloud/base.qcow2` |
| `cloud/seed.iso` | `$HOME/mobile-lab/xa2-01-cloud/seed.iso` |
| `kernel/Image` | `$HOME/mobile-lab/xa2-01-hz100/Image` |

Keep `kernel.config` and `verification.json` with the private preparation records. Stage
`scripts/termux-kernel-start.sh` in Termux, then run it from its containing directory to select
the extracted baseline kernel:

```sh
bash termux-kernel-start.sh
```

The launcher verifies the pinned kernel and base-image hashes, requires the seed and rejects a
start if its recorded PID is live. If absent, it creates `xa2-01-hz100/root.qcow2` as an overlay
with backing path `../xa2-01-cloud/base.qcow2`, then expands the virtual disk to 4 GiB. Preserve
that backing-file relationship; do not replace or edit the base beneath an existing overlay.

Boot uses `virt,gic-version=3`, multithreaded TCG, CPU `max,pauth-impdef=on`, two vCPUs and 1024 MiB
RAM. The direct kernel command line selects `root=/dev/vda2`, ext4 and `ttyAMA0`. Runtime state is
`qemu.pid`, `console.log` and `monitor.sock` under `$HOME/mobile-lab/xa2-01-hz100`.

The alternative `termux-cloud-start.sh` boots the cloud image through UEFI. The earlier
`termux-vm-start.sh` and `guest-install.sh` belong to the ISO installation experiment. They are
not the current guest preparation path. All launchers share the same phone ports; their per-directory
PID checks do not coordinate multiple launchers. Keep only one lab guest using those ports.

### Replacement kernel: pending build and boot validation

After a successful build, the optional launcher route requires all three files from
`$lab_state/kernel-build` to be transferred together into
`$HOME/mobile-lab/kernel-7.1.5-agro1` inside Termux:

- `Image`
- `kernel.config`
- `build-metadata.json`

The command interface is:

```sh
bash termux-kernel-start.sh "$HOME/mobile-lab/kernel-7.1.5-agro1"
```

This route is prepared but has not yet booted a completed build. The launcher checks the expected
source and baseline hashes, release `7.1.5-agro1`, raw Image and resolved-configuration hashes,
ARM64 Image format, HZ 100 and required built-in network/direct-boot features before side effects.
It retains the existing cloud disk and rejects a start while the recorded QEMU PID is live.
Local metadata checks do not establish a build or origin attestation. Omitting the directory
argument continues to select the extracted baseline kernel.

## Guest access and manual configuration

Forward host TCP 18024 to phone TCP 10022. Verify the guest SSH fingerprint independently and save
it in `guest_known_hosts` beside the host's dedicated key. `scripts/xa2-guest-ssh id` connects as
`alpine`; administration uses `doas`. The measured guest accepts key-only SSH.

The working guest includes these manual changes, which are not reproduced by the preparers or
launcher:

- Replace incompatible helper-based `mdev` with `mdevd`; its service is started.
- Enable the cgroups service and verify a pure cgroup v2 hierarchy, including `cpu`, `cpuset`, `io`,
  `memory` and `pids` controllers.
- Expand partition 2 while preserving its starting sector 2048 and the EFI partition, refresh the
  kernel's partition view and grow ext4. The measured root grew from 156.6 MiB to 3.7 GiB.
- Place the verified K3s binary at `/usr/local/bin/k3s`. Its first execution extracted approximately
  236 MiB of assets; a subsequent measurement showed approximately 3.1 GiB available on `/`.

The disk expansion used a partition-table dry run and checked the target before changing it.
These observations describe the existing guest; a fresh image still requires those steps and
independent validation. Do not infer filesystem growth from the launcher's virtual-disk resize.

## K3s compatibility check

On the prepared guest, the following commands have been exercised:

```sh
/usr/local/bin/k3s --version
doas /usr/local/bin/k3s check-config
```

The binary reports `v1.36.4+k3s1` (`4dedb15b`), built with Go `1.26.7`. The configuration check
currently exits `4` and reports missing `CONFIG_IP_NF_TARGET_REJECT`,
`CONFIG_NETFILTER_XT_MATCH_MULTIPORT` and `CONFIG_NETFILTER_XT_MATCH_STATISTIC`.
A replacement kernel still needs verification. No K3s service or node has been brought up.

## Prepared air-gap images and smoke workload

The official K3s ARM64 air-gap archive has been staged and verified inside the guest:

- Size: `176533504` bytes.
- SHA-256: `d84268705e70019d76f4ef1c27cbb9d0bf480486e1d216103ebc732cfbd35bbb`.

Staging and checksum verification do not establish a container-runtime import or a running Pod.
The prepared [smoke manifest](../manifests/smoke.yaml) uses the BusyBox image pinned by digest from
that archive. It defines namespace `agro-lab`, a single HTTP replica running as UID/GID 65534,
a read-only root filesystem, a memory-backed `/www` volume, an HTTP readiness probe and
NodePort 30080. The YAML has been parsed offline but has not been applied. Deployment remains
pending a compatible kernel and a working K3s node.

## Port mappings and recovery

| Host loopback port | Phone loopback port | Guest destination | Purpose |
|---|---|---|---|
| 18022 | 8022 | None | Termux management SSH |
| 18023 | 10023 | QEMU serial device | Guest console |
| 18024 | 10022 | TCP 22 | Guest SSH, verified |
| 16443 | 16443 | TCP 6443 | Future Kubernetes API |
| 18080 | 10080 | TCP 30080 | Future test service |

ADB provides host-to-phone mappings; QEMU provides the guest service forwards. After a transport
loss, identify the phone again and recreate the dedicated forwards as needed. The existing QEMU
process and guest SSH survived one actual ADB transport loss and recovery.

Separate screen-off samples 341 seconds apart retained the same guest boot ID while Android's
reported sleep duration increased from approximately 44 to 50 minutes. This establishes guest
continuity at those observations. Reboot autostart, power-loss recovery, longer-duration operation
and bidirectional networking between two phone guests remain untested.
