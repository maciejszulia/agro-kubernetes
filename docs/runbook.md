# First-phone runbook

The first Xperia has a native control plane and a Ready Linux guest worker. Smoke reached
1/1 Running and served exact HTTP responses, but later requests timed out despite Pod readiness.
CoreDNS is Running but 0/1 Ready. Stable HTTP, DNS, policy enforcement and API-to-kubelet proxy
reliability remain open. See the [verification record](verification.md).

## Prerequisites

- An identified Sony Xperia H3113 with authorized USB debugging and Termux installed.
- A management host with ADB, OpenSSH, Bash, Python 3.11 or newer, `curl` and `bsdtar`.
- A dedicated Ed25519 key and separate Termux/guest known-hosts files outside the repository.
- Termux OpenSSH, Python 3, QEMU, `qemu-img`, PRoot and an active termux-services supervisor.
- App-private storage for the cloud base, a growing 4 GiB overlay, seed, kernel and logs.

The worker-kernel build also requires access to a Docker daemon and host capacity
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

## Prepare K3s and the native control plane

The control plane uses the unmodified official K3s ARM64 launcher. On the management host:

```sh
lab_state="${XDG_STATE_HOME:-$HOME/.local/state}/mobile-lab/xa2-01"
python3 scripts/prepare-k3s.py --output "$lab_state/k3s"
```

[prepare-k3s.py](../scripts/prepare-k3s.py) downloads or reuses `k3s-arm64` for v1.36.4+k3s1 and
requires SHA-256 `c920706346d5ad4e5cd3c7bf1bb09ce71ebe07fec829e513e40f1caf98aed8bb`.
It preserves a conflicting existing binary and promotes only a checksum-matching download.

Inside Termux, create private state `$HOME/mobile-lab/native-control` and stage the executable
binary as `bin/k3s` beneath it. Keep the state directory private and the staged binary executable.
Stage [termux-native-control.sh](../scripts/termux-native-control.sh) separately. With
`phone_node_ip` set locally to the phone's current IPv4 address, its command interface is:

```sh
bash termux-native-control.sh --node-ip "$phone_node_ip"
```

The address is required because Android default-route discovery fails. Keep its actual value
outside the repository. The helper checks the binary hash, existing state, prerequisites and
service-file identity before setup. It refuses incompatible existing files rather than adopting
an unrelated service. An existing termux-services supervisor is required.

The helper prepares the private configuration and extracts the verified launcher's bundled
server payload through installed PRoot. The service runs PRoot with `-r /` and the state working
directory, then launches the unmodified server payload. This is syscall compatibility only:
there is no separate distro, fake UID/kernel or seccomp override. The runtime remains Termux
UID 10179 with Android seccomp mode `2`.

The scoped runit service is `agro-k3s-control`. Configuration, data, kubeconfig and bounded logs
remain under `$HOME/mobile-lab/native-control`; the kubeconfig is mode `0600`. The rootless
node-password path is `data/agent/etc/rancher/node` below that state directory. The API binds
`127.0.0.1:16443`, advertises `10.0.2.2`, includes both addresses as TLS SANs, and uses egress
selector mode `cluster`. The rootless/disable-agent path has not created RootlessKit namespaces
in the observed runtime.

The manually configured native control plane passed all `/readyz` checks, including RBAC.
The full local suite passes 48 tests, including the native control and air-gap helpers. Executing the setup
helper on the phone remains unverified. Supervision setup is not a readiness check, and API
readiness is not proof of a joined worker.

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

## Build the worker kernel

The upstream Linux 7.1.5-agro1 build is complete. Its embedded configuration matches the build
output, the guest boots, and K3s `check-config` passes. The measured Image is 63,461,888 bytes with
SHA-256 `257e234ec595d1d51ff3935d9e52500267d70c48f37b7bb47d180b6db338902d`.

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
The launcher validates the completed build artifacts together before using the kernel.

## Stage and boot the worker guest

Create the target directories inside Termux app-private storage and transfer these artifacts:

| Prepared host artifact | Phone destination |
|---|---|
| `cloud/generic_alpine-3.24.1-aarch64-uefi-tiny-r0.qcow2` | `$HOME/mobile-lab/xa2-01-cloud/base.qcow2` |
| `cloud/seed.iso` | `$HOME/mobile-lab/xa2-01-cloud/seed.iso` |
| `kernel-build/Image` | `$HOME/mobile-lab/kernel-7.1.5-agro1/Image` |
| `kernel-build/kernel.config` | `$HOME/mobile-lab/kernel-7.1.5-agro1/kernel.config` |
| `kernel-build/build-metadata.json` | `$HOME/mobile-lab/kernel-7.1.5-agro1/build-metadata.json` |

Stage `scripts/termux-kernel-start.sh` in Termux, then run it from its containing directory:

```sh
bash termux-kernel-start.sh "$HOME/mobile-lab/kernel-7.1.5-agro1"
```

The launcher validates the expected source/baseline hashes, release `7.1.5-agro1`, Image and
resolved-configuration hashes, ARM64 format, HZ 100 and required built-ins before side effects.
It also verifies the cloud base, requires the seed and rejects a start while its recorded PID is
live. These local consistency checks do not establish an origin attestation.

If absent, the launcher creates `xa2-01-hz100/root.qcow2` as a 4 GiB overlay referencing
`../xa2-01-cloud/base.qcow2`. Preserve that backing-file relationship. The current worker profile
reuses the existing disk and kernel with two vCPUs, 768 MiB RAM and a 128 MiB TCG translation
buffer. It uses GICv3, CPU `max,pauth-impdef=on`, ext4 root `/dev/vda2` and console `ttyAMA0`.
The guest API host forward is removed; the native control plane owns phone port 16443.

Runtime state remains `qemu.pid`, `console.log` and `monitor.sock` under
`$HOME/mobile-lab/xa2-01-hz100`. Guest SSH, console and HTTP ports remain unchanged.
The worker is Ready, but the reduced profile has no verified workload-capacity claim.

The launcher's no-argument mode selects the extracted Podroid baseline Image under
`xa2-01-hz100/Image` for comparison. That kernel lacks three required network options and is not
the current worker kernel. `termux-cloud-start.sh` is the earlier UEFI comparison path;
`termux-vm-start.sh` and `guest-install.sh` belong to the earlier ISO experiment. Keep only one
lab guest on the shared ports; per-directory PID checks do not coordinate different launchers.

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

The binary reports `v1.36.4+k3s1` (`4dedb15b`), built with Go `1.26.7`. On the built
`7.1.5-agro1` kernel, the configuration check reports `STATUS: pass` and exits `0`; the measured
run took 442 seconds. This verifies the guest kernel gate, not worker registration or a running Pod.

## Install the separate guest agent

[config/k3s-agent.yaml](../config/k3s-agent.yaml) has been applied as
`/etc/rancher/k3s/native-agent.yaml` inside the guest:

| Setting | Value |
|---|---|
| Node name | `xa2-01` |
| Data directory | `/var/lib/rancher/k3s-native-agent` |
| Server | `https://10.0.2.2:16443` |
| Private token file | `/etc/rancher/k3s/native-agent-token` |
| Local load-balancer port | `7444` |
| Resolver configuration | `/etc/resolv.conf` |
| Proxy mode | `iptables` |

This is a manual installation using the
[official installer for v1.36.4+k3s1](https://raw.githubusercontent.com/k3s-io/k3s/v1.36.4%2Bk3s1/install.sh).
There is no worker-provisioning helper in this repository.

1. Keep the earlier VM server/agent units stopped. Verify the existing `/usr/local/bin/k3s` binary
   against the pinned hash before using it.
2. Install the configuration and token as root-owned mode `0600` files. Transfer the token from
   the native control plane's private `data/server/agent-token` through a private pipe; never
   print it or place it in a command argument.
3. Create the fresh `/var/lib/rancher/k3s-native-agent` directory with mode `0700`. Stage the
   verified air-gap archive under its `agent/images` directory. The observed installation used
   a hard link to the already verified archive and a fresh image cache.
4. Stage the verified official installer as `/tmp/agro-install-k3s.sh`. The following commands
   were executed from a guest root shell:

```sh
INSTALL_K3S_SKIP_DOWNLOAD=true INSTALL_K3S_SKIP_START=true INSTALL_K3S_NAME=native-agent sh /tmp/agro-install-k3s.sh agent --config /etc/rancher/k3s/native-agent.yaml
rc-service k3s-native-agent start
```

The installer created the separate OpenRC unit and enabled it in the default runlevel. It also
wrote its shared kill-all helper; older VM units remained stopped. For a fresh preparation run,
the official installer supports `INSTALL_K3S_BIN_DIR_READ_ONLY=true` to avoid binary-directory
writes and `INSTALL_K3S_SKIP_ENABLE=true` alongside `INSTALL_K3S_SKIP_START=true` to defer enabling
and starting the service. Those extra guards were not used in the recorded installation above.

The agent registered `xa2-01` as Ready with no taints or pressure, and its CSINode appeared.
The reported container runtime is containerd 2.3.4-k3s1. A transient CSI registration `NotFound`
recovered automatically; it did not require an agent restart.

## Experimental sandbox timeout

The first `RunPodSandbox` call exceeded the default four-minute deadline. The pinned CRI client
uses twice `runtimeRequestTimeout` for that operation. The experimental
[config/kubelet-tcg.conf](../config/kubelet-tcg.conf) sets this value to `5m`, producing a ten-minute
sandbox deadline. This is a local experiment, not an upstream TCG recommendation. See
[CRI timeout handling](https://github.com/k3s-io/kubernetes/blob/5f3efbf9f6b592422439471c5fe1a1ab2887e189/staging/src/k8s.io/cri-client/pkg/remote_runtime.go#L220-L238).

After confirming that the target did not exist, the drop-in was installed as a root-owned mode
`0600` file at `/var/lib/rancher/k3s-native-agent/agent/etc/kubelet.conf.d/10-agro-tcg.conf`.
Stage the repository file there without replacing an unrelated configuration, then restart only
the guest agent. The recorded root-shell command returned exit `0`:

```sh
rc-service k3s-native-agent restart
```

The service reported started and native API readiness remained healthy. Smoke later reached
Running; that observation does not isolate the setting's effect or establish stable availability.
K3s supports kubelet configuration drop-ins; see
[kubelet configuration files](https://docs.k3s.io/installation/configuration#kubelet-configuration-files).

## Prepared air-gap images and smoke workload

The official K3s ARM64 air-gap archive has been staged and verified inside the guest:

- Size: `176533504` bytes.
- SHA-256: `d84268705e70019d76f4ef1c27cbb9d0bf480486e1d216103ebc732cfbd35bbb`.

The [smoke manifest](../manifests/smoke.yaml) uses the BusyBox image pinned by digest from
that archive. It defines namespace `agro-lab`, a single HTTP replica running as UID/GID 65534,
a read-only root filesystem, a memory-backed `/www` volume, an HTTP readiness probe and
NodePort 30080. Server-side validation and apply passed. The initial 180-second rollout timed
out; smoke subsequently reached 1/1 Running with zero restarts. Exact responses were observed
through the direct Pod, guest NodePort, phone forward and laptop USB forward. Later requests
timed out, so stable HTTP remains unverified. CoreDNS is Running but 0/1 Ready and DNS is unverified.

### Optional reduced ARM64 archive

[prepare-airgap.py](../scripts/prepare-airgap.py) derives a fixed lab subset from the original
archive without changing the source or image pins. From the repository root, with the verified
official archive stored privately as `official.tar`:

```sh
lab_state="${XDG_STATE_HOME:-$HOME/.local/state}/mobile-lab/xa2-01"
python3 scripts/prepare-airgap.py --source "$lab_state/official.tar" --output "$lab_state/derived.tar"
```

The source must match SHA-256
`d84268705e70019d76f4ef1c27cbb9d0bf480486e1d216103ebc732cfbd35bbb`.
The selected images are BusyBox 1.37.0, pause 3.10.2 and CoreDNS 1.14.6. The helper verifies their
pinned indexes, ARM64 manifests, configurations and layers, and retains 24 original blobs in
27 archive entries. It refuses a conflicting existing output.

The derived archive is 23,388,160 bytes versus 176,533,504 bytes for the source, a reduction of
86.75%. Its SHA-256 is `0417fbaaa8278fcecb236f516a990a7e1bc001039ce879a829a88cf76eeffac4`.
Only the ARM64 dependency closure is included. Root image-index blobs remain unchanged and still
reference upstream non-ARM descriptors whose blobs are absent. Runtime import of this derived
archive and any startup or transfer-speed benefit have not been verified.

## Optional network-policy verification

[manifests/network-policy-probe.yaml](../manifests/network-policy-probe.yaml) has not been applied.
Run this optional test only after smoke HTTP, cluster DNS and remote execution work. The fixture
temporarily restricts ingress to the smoke Pods, so unrelated HTTP probes may fail while it is active.
Current intermittent HTTP failures, unverified DNS and API-to-kubelet TLS timeouts prevent a
conclusive policy test; do not classify those failures as policy enforcement.

1. Successfully query namespace `agro-lab` and confirm that both Pod `network-policy-probe` and
   NetworkPolicy `smoke-probe-ingress` are absent. A lookup error is not proof of absence. Stop if
   either name already exists, and inspect other policies that select the smoke Pods.
2. Validate the fixture against the server, then create its two objects. Record the UID of each
   successfully created object, including partial-creation results. Do not adopt existing objects.
3. Wait for the probe Pod to run. With its initial `access=allowed` label, make a bounded HTTP
   request to the smoke Service's numeric cluster IP from inside that Pod. Require the expected
   `agro-kubernetes` response and a zero command exit code.
4. Change only the created probe Pod's label to `access=denied`. After bounded policy-propagation
   retries, require a connection rejection or timeout from the same request. Use an in-container
   start marker and capture the request exit status: failed exec transport, DNS resolution, a
   missing executable or an HTTP application error does not prove policy enforcement.
5. Restore `access=allowed` and require the same successful HTTP response again. Record all three
   outcomes separately; a denied request alone is insufficient.
6. Delete only the Pod and NetworkPolicy created by this test after confirming that their UIDs
   still match. On partial failure, clean up only confirmed creations. Preserve the namespace,
   smoke workload, CoreDNS and all pre-existing objects.

Allow, deny, restore and cleanup remain unverified. These steps do not constitute a passing
network-policy result until their runtime evidence is recorded.

## Port mappings and recovery

| Host loopback port | Phone loopback port | Guest destination | Purpose |
|---|---|---|---|
| 18022 | 8022 | None | Termux management SSH |
| 18023 | 10023 | QEMU serial device | Guest console |
| 18024 | 10022 | TCP 22 | Guest SSH, verified |
| 16443 | 16443 | None | Native control-plane API; no guest API forward |
| 18080 | 10080 | TCP 30080 | Smoke NodePort; successful responses observed, stable availability unverified |

ADB provides host-to-phone mappings; QEMU provides only the guest SSH and HTTP forwards.
The native API owns phone `127.0.0.1:16443`. The guest's server endpoint is
`https://10.0.2.2:16443`, using the SLIRP host gateway. This is a local-phone route; the second
phone still needs a separately validated network design.

After a transport loss, identify the phone again and recreate dedicated forwards as needed.
Earlier QEMU and guest SSH checks survived an ADB transport loss. After a later USB outage,
management access recovered and the native control plane retained the same service process for
over 42 minutes with full readiness checks passing. The guest subsequently registered as Ready.

A later controlled 30-second outage of the dedicated ADB server preserved the smoke Pod UID,
container ID, restart count and Ready state on reconnection. Phone-side HTTP probes timed out
both during and after the outage, so HTTP continuity failed. Later phone and laptop NodePort
requests also hit ten-second timeouts despite readiness. An API-to-kubelet proxy TLS handshake
hit its ten-second deadline. The cause is unresolved; do not infer a CPU or USB cause from these
observations. Record response evidence separately from Pod identity and readiness.

Separate screen-off samples 341 seconds apart retained the same guest boot ID while Android's
reported sleep duration increased from approximately 44 to 50 minutes. This establishes guest
continuity at those observations. Reboot autostart, power-loss recovery, longer-duration operation
and bidirectional networking between two phone guests remain untested.
