# agro-kubernetes

A hobby Kubernetes lab using Sony Xperia H3113 phones while retaining locked, unrooted Android.
The current design separates a native Termux control plane from a Linux guest running kubelet
and containerd. The target remains a two-phone cluster; the T470p
provides management and build tooling.

## Current status

The guest worker `xa2-01` is **Ready**, and the smoke Pod reached **1/1 Running** with zero
restarts. Exact HTTP responses were observed through the guest, phone and laptop forwarding
paths. **Stable HTTP availability is not established:** later probes timed out despite Pod
readiness. CoreDNS is Running but 0/1 Ready; DNS and network-policy validation remain open.

| Component | Latest verified state |
|---|---|
| Phone | H3113, Android 9 / 50.2.A.3.77; locked and unrooted; Termux UID 10179 |
| Control plane | Unmodified K3s v1.36.4+k3s1, agentless/rootless, running natively in Termux |
| Linux syscall compatibility | Installed PRoot 5.1.107.95 in passthrough mode; Android seccomp remains enabled |
| Supervision | Dedicated `agro-k3s-control` runit service with bounded private logs |
| Guest kernel | Upstream Linux 7.1.5-agro1 built and booted; K3s `check-config` passed with exit 0 |
| Worker profile | Same Alpine cloud disk and kernel; two vCPUs, 768 MiB RAM and a 128 MiB TCG translation buffer |
| Guest access | Key-only SSH as `alpine`, `doas`, pure cgroup v2 and `mdevd` verified |
| Worker | `xa2-01` Ready with no taints or pressure; CSINode present; containerd 2.3.4-k3s1 |
| Second Xperia | Not provisioned; cross-phone networking unverified |
| Smoke workload | 1/1 Running, zero restarts; exact `agro-kubernetes` HTTP responses observed |
| Availability | Controlled 30-second ADB-server outage preserved Pod identity/readiness, but HTTP continuity failed; later NodePort probes also timed out |
| DNS and API proxy | CoreDNS Running 0/1; DNS unverified; API-to-kubelet TLS handshake timeout unresolved |

The successful HTTP observations establish reachability at those points, not sustained service.
No cause has been established for the later timeouts. See [verification](docs/verification.md)
for the successful observations, failed continuity check and remaining limits.

## Architecture

The native control plane uses the Android CPU directly. PRoot supplies Linux syscall compatibility
without a separate distribution, fake UID, fake kernel version or seccomp override. The observed
combined rootless/agentless K3s path does not create RootlessKit namespaces.

QEMU supplies the Linux kernel, guest-root privileges and cgroups required by the worker.
The native API owns phone loopback port 16443; the guest reaches it through the QEMU user-network
gateway `10.0.2.2`. The former guest API forward is removed. Worker registration is verified;
the smoke workload has responded, while stable networking remains unverified. See
[architecture](docs/architecture.md).

## Prerequisites and entry points

The setup requires authorized USB debugging, Termux and a Linux management host with ADB, OpenSSH,
Bash, Python 3.11 or newer, `curl` and `bsdtar`. Kernel compilation uses Docker. Phone-side control
requires PRoot and termux-services. Keys, node addresses, tokens, downloaded artifacts and runtime
state stay outside Git.

| Entry point | Purpose |
|---|---|
| [termux-inventory.sh](scripts/termux-inventory.sh), [termux-access.sh](scripts/termux-access.sh) | Inspect Termux and configure dedicated loopback SSH |
| [termux-install-qemu.sh](scripts/termux-install-qemu.sh) | Install QEMU and check its tools and firmware |
| [prepare-k3s.py](scripts/prepare-k3s.py), [termux-native-control.sh](scripts/termux-native-control.sh) | Prepare the pinned K3s binary and native control-plane service; on-phone setup-helper execution unverified |
| [prepare-airgap.py](scripts/prepare-airgap.py) | Derive the pinned three-image ARM64 lab archive; runtime import unverified |
| [prepare-cloud.py](scripts/prepare-cloud.py), [prepare-kernel.py](scripts/prepare-kernel.py) | Prepare the cloud image, seed and baseline kernel configuration |
| [build-kernel.sh](scripts/build-kernel.sh) | Build the ARM64 kernel with the required network features |
| [termux-kernel-start.sh](scripts/termux-kernel-start.sh) | Launch the Linux guest with validated kernel artifacts |
| [xa2-ssh](scripts/xa2-ssh), [xa2-guest-ssh](scripts/xa2-guest-ssh) | Connect to Termux and the guest |
| [k3s-agent.yaml](config/k3s-agent.yaml) | Applied configuration for the separate guest agent service |
| [kubelet-tcg.conf](config/kubelet-tcg.conf) | Experimental runtime timeout; sustained workload behavior unverified |
| [smoke.yaml](manifests/smoke.yaml) | Prepared non-root BusyBox HTTP workload and NodePort service |
| [network-policy-probe.yaml](manifests/network-policy-probe.yaml) | Optional allow/deny/restore test fixture; not applied |

The [runbook](docs/runbook.md) distinguishes scripted preparation from manual agent installation
and pending workload validation. No automated end-to-end cluster bootstrap is claimed.

## Verification and limitations

Run local checks from the repository root:

```sh
python3 -B -m unittest discover -s tests -v
for script in scripts/*.sh; do
    bash -n "$script" || exit
done
sh -n scripts/guest-install.sh
sh -n scripts/xa2-ssh
sh -n scripts/xa2-guest-ssh
git diff --check
```

The published foundation passed 28 tests in the main repository CI. The full local suite now
passes 48 tests, including nine tests for the derived air-gap archive. On-phone setup-helper execution remains
unverified; the earlier passing API checks came from the manually configured equivalent.
Runtime evidence and test coverage are recorded in
[verification](docs/verification.md). Stable HTTP, DNS, policy enforcement, Android reboot,
power loss and longer-duration operation remain open.

The [reception panel](docs/reception-target.md) is a future workload specification only.
No business application, existing data, service or production credential has moved to a phone.
