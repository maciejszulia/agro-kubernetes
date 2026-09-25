# Verification record

Snapshot: 2026-09-26. The first guest worker is Ready and smoke reached 1/1 Running with zero
restarts. Exact HTTP responses were observed, including the laptop USB-forwarded request at
00:13:36 +02:00. Later requests timed out despite readiness: stable HTTP availability and
continuity are not established. CoreDNS is Running but 0/1 Ready; DNS and policy remain unverified.

## Current results

| Check | Result | Evidence |
|---|---|---|
| First Xperia | Verified | H3113, Android 9 / 50.2.A.3.77; locked and unrooted |
| Termux control plane | Ready checks passed | Unmodified K3s v1.36.4+k3s1; all native `/readyz` checks, including RBAC |
| Runtime identity | Verified | Termux UID 10179; Android seccomp mode `2` |
| Compatibility path | Verified | PRoot 5.1.107.95 passthrough; no separate distro, fake UID/kernel or seccomp override |
| Rootless/agentless behavior | Observed | No RootlessKit namespaces created in the combined upstream path |
| Supervision | Present | Dedicated `agro-k3s-control` runit service with bounded private logs |
| Built kernel | Built and booted | Linux 7.1.5-agro1; embedded configuration matches |
| Guest kernel gate | Passed | `k3s check-config` reported `STATUS: pass`, exit `0`; measured duration 442 seconds |
| Guest worker profile | Prepared | Same disk/kernel; two vCPUs, 768 MiB RAM, 128 MiB TCG translation buffer |
| Worker registration | Passed | `xa2-01` Ready at 21:42:27 UTC; no taints or pressure; CSINode present |
| Container runtime | Reported | containerd 2.3.4-k3s1 |
| Native API continuity | Passed for the observed outage | Same service process after over 42 minutes; full readiness passed after USB recovery |
| Smoke deployment | Applied | Server validation and apply passed; initial 180-second rollout timed out |
| Smoke Pod | Running | 1/1 Ready, zero restarts; exact HTTP responses observed |
| CoreDNS | Running, not Ready | 0/1 Ready; DNS unverified |
| Runtime timeout experiment | Installed | Five-minute request setting; ten-minute sandbox deadline; smoke later ran, causal benefit unverified |
| HTTP reachability | Observed | Exact `agro-kubernetes` response through direct Pod, guest NodePort, phone and laptop forwarding |
| HTTP continuity | Failed | Phone probes timed out during and after the controlled ADB-server outage |
| Stable HTTP and API proxy | Unresolved | Later phone/laptop NodePort and API-to-kubelet TLS handshake reached ten-second timeouts |
| Network policy | Unverified | Fixture not applied; no allow/deny/restore result |
| Second Xperia | Unprovisioned | Cross-phone network and second-node behavior unverified |
| Business workloads | Absent | No business application, existing data or production credentials transferred |

## Artifact identity

| Artifact | Verified identity |
|---|---|
| K3s ARM64 binary | v1.36.4+k3s1; SHA-256 `c920706346d5ad4e5cd3c7bf1bb09ce71ebe07fec829e513e40f1caf98aed8bb` |
| Built Linux Image | 7.1.5-agro1; 63,461,888 bytes; SHA-256 `257e234ec595d1d51ff3935d9e52500267d70c48f37b7bb47d180b6db338902d` |
| Official ARM64 air-gap archive | 176,533,504 bytes; SHA-256 `d84268705e70019d76f4ef1c27cbb9d0bf480486e1d216103ebc732cfbd35bbb`; verified inside the guest |
| Derived three-image ARM64 archive | 23,388,160 bytes; SHA-256 `0417fbaaa8278fcecb236f516a990a7e1bc001039ce879a829a88cf76eeffac4`; runtime import unverified |

The built kernel includes the eleven network options in
[config/k3s-kernel.config](../config/k3s-kernel.config). Source, baseline, resolved-configuration
and Image hashes are recorded by the build. These checks do not establish bitwise reproducibility
or an upstream attestation. The Podroid APK used to obtain the original baseline was never installed.

## Control-plane comparison

| Attempt | Observed result |
|---|---|
| Full K3s inside the two-vCPU/1 GiB TCG guest | Repeated authentication/controller bootstrap timeouts |
| Agentless control plane inside that guest | API ready once; later controller-manager timeout and restart |
| Agentless/rootless control plane natively in Termux | All `/readyz` checks passed, including RBAC |

No OOM was found in the guest failures. An isolated public-input scrypt probe used Go 1.26.7 with
`golang.org/x/crypto` v0.47.0, the effective version selected by a `go.mod` replacement. The probe
made two calls with `N=32768`, `r=8`, `p=1` and output length 64 bytes:

| Environment | Recorded elapsed time |
|---|---|
| Native Termux | 0.858 seconds |
| QEMU guest | 14.501 seconds |

There is one sample per environment and the available CPU counts differ. The result is a bounded
comparison, not a universal speed ratio or a complete causal diagnosis of the bootstrap failures.

Native executable lookup initially failed when Android blocked `faccessat2`. PRoot returned
`ENOSYS`, and Go used its normal permission fallback. Android seccomp remained enabled. The
control plane also required an explicit phone node IPv4 because default-route discovery failed.

## Guest preparation and continuity

The guest uses the verified Alpine 3.24.1 tiny ARM64 cloud base, pure cgroup v2, `mdevd`, key-only
SSH as `alpine` and `doas`. Manual filesystem expansion grew the root from 156.6 MiB to 3.7 GiB
while preserving partition 2's start sector 2048 and the EFI partition. A measurement after K3s
asset extraction recorded 511.9 MiB used and approximately 3.1 GiB available; later artifact
staging changes free space.

The earlier extracted Linux 7.1.5 kernel failed three required K3s options. Building upstream
7.1.5-agro1 resolved that configuration gate. The earlier Alpine 3.24.2 ISO route reached OpenRC
but never established a usable login and is no longer the current boot path.

QEMU and guest SSH survived an actual ADB transport loss and recovery. Two separate screen-off
samples 341 seconds apart retained the same guest boot ID and unchanged Android wake/sleep
timestamps; Android's reported sleep duration increased from approximately 44 to 50 minutes.
Both samples reported 100% battery and 35.5 °C. These are guest continuity observations only;
they do not validate the later native control-plane service or a Kubernetes workload.

After a later USB outage, management access and pinned SSH recovered. The native control service
retained the same process for over 42 minutes and all `/readyz` checks passed. The guest then joined
through a separate `k3s-native-agent` OpenRC unit with fresh private data, token and configuration.
The older VM units remained stopped. A transient CSI `NotFound` resolved automatically, and the
CSINode was present when the worker reached Ready.

## Workload observations and unresolved availability

The smoke manifest passed server-side validation and was applied. Its initial 180-second rollout
timed out while smoke and CoreDNS remained `ContainerCreating`. The first `RunPodSandbox` call
exceeded its default four-minute deadline.

The experimental [kubelet drop-in](../config/kubelet-tcg.conf) was installed with mode `0600`
under the agent's private data directory, and only `k3s-native-agent` was restarted. The restart
returned `0`, the unit reported started, and native API readiness remained healthy. The five-minute
runtime request setting yields a ten-minute sandbox deadline in the pinned implementation.
Smoke subsequently reached 1/1 Running with zero restarts. This does not isolate the timeout
setting's effect or establish stable availability; no upstream TCG recommendation is claimed. See the
[timeout implementation](https://github.com/k3s-io/kubernetes/blob/5f3efbf9f6b592422439471c5fe1a1ab2887e189/staging/src/k8s.io/cri-client/pkg/remote_runtime.go#L220-L238).

All four paths below returned the exact `agro-kubernetes` response:

| Request path | Recorded elapsed time |
|---|---|
| Guest to direct Pod address | Not recorded here |
| Guest NodePort | 0.62 seconds |
| Phone NodePort forward | 0.79 seconds |
| Laptop USB forward | 0.360 seconds at 2026-09-26 00:13:36 +02:00 |

These are individual observations, not a latency benchmark or proof of sustained availability.

A controlled 30-second outage of the dedicated ADB server preserved the smoke Pod UID, container
ID, restart count and Ready state on reconnection. Phone-side HTTP probes timed out both during
and after that outage. The HTTP continuity check therefore failed; preserved Pod identity does
not establish service continuity.

Later manual phone and laptop NodePort requests hit ten-second timeouts despite readiness.
An API-to-kubelet proxy TLS handshake also reached its ten-second deadline. Their cause remains
unresolved; CPU or USB causation has not been established. CoreDNS is Running but 0/1 Ready,
and no successful DNS query is recorded.

The [network-policy fixture](../manifests/network-policy-probe.yaml) has not been applied.
DNS, policy allow/deny/restore and policy-test cleanup remain unverified.

## Derived air-gap archive

[prepare-airgap.py](../scripts/prepare-airgap.py) retains the pinned BusyBox, pause and CoreDNS
images from the official source archive: 24 original blobs in 27 entries, totaling 23,388,160
bytes. This is 86.75% smaller than the 176,533,504-byte source. Source and image pins are unchanged.
Only ARM64 dependency blobs are retained; root indexes preserve upstream non-ARM descriptors.
Runtime import and speed benefits from the derived archive remain unverified.

## Local and CI checks

The published foundation passed 28 tests in the main repository CI: ten cloud-preparation tests,
nine kernel-extraction tests, four build-configuration tests and five launcher tests. These use
local fixtures. The full local suite now passes 48 tests, including nine air-gap-preparer tests;
that result is separate from the published 28-test CI baseline. On-phone setup-helper execution
remains unverified. The earlier passing native API checks came from the manually configured
equivalent.

The actual Termux safeguards also accepted a pristine ISO-install disk and its dedicated SSH
process/listener with exit `0`, and rejected a data-bearing disk and an unrelated live PID with
exit `1`. The smoke manifest has also passed server validation and apply. Static checks do not
replace the separate node and workload measurements above.

Run the current local checks from the repository root:

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

Raw logs, keys, node addresses, tokens, downloaded artifacts and guest disks remain outside Git.

## Remaining acceptance criteria

1. Diagnose the HTTP and API-to-kubelet timeouts and establish repeatable service availability.
2. Verify CoreDNS readiness, DNS queries and optional policy allow/deny/restore.
3. Verify setup-helper execution on the phone and repeat startup of the control-plane/worker combination.
4. Provision the second Xperia and validate the cross-phone API and pod data network.
5. Measure reboot, power-loss, transport-loss and longer-duration recovery of the complete system.
6. Verify runtime import of the derived air-gap archive before claiming operational benefits.

One Ready worker does not complete workload validation or the two-phone Kubernetes objective.
