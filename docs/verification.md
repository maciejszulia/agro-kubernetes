# Verification record

Results as of 2026-09-25. The first phone has a usable Linux guest. Kubernetes readiness remains
blocked by missing kernel features.

## Observed results

| Check | Result | Evidence |
|---|---|---|
| First device | Verified | H3113, Android 9 / 50.2.A.3.77; locked bootloader, verified boot green, unrooted Android |
| Termux management | Passed | Termux 0.118.3; dedicated key-only loopback SSH through ADB |
| QEMU | Passed | QEMU and qemu-img 11.0.3 |
| Cloud base | Verified | Official Alpine 3.24.1 tiny aarch64 image; pinned SHA-512 matched |
| Standalone kernel | Verified artifact and running kernel | Linux 7.1.5 extracted from Podroid v1.2.9; APK and Image hashes checked; APK never installed |
| Current boot | Passed | Direct kernel boot, `root=/dev/vda2`; GICv3, multithreaded TCG, `max`, two vCPUs, 1024 MiB |
| Guest administration | Passed | Key-only SSH as `alpine`; `doas` available |
| Device management | Passed | `mdevd` service started after replacing incompatible helper-based `mdev` |
| Cgroups | Passed | Pure cgroup v2; cgroups service started; `cpu`, `cpuset`, `io`, `memory`, `pids` and additional controllers present |
| Root filesystem growth | Passed | Manual expansion from 156.6 MiB to 3.7 GiB; approximately 3.1 GiB free after K3s asset extraction |
| ADB transport loss | Passed for the observed event | QEMU and guest SSH survived actual transport loss and recovery |
| Screen-off guest continuity | Observed | Two samples 341 seconds apart; same guest boot ID and Android wake/sleep timestamps |
| K3s binary | Passed | Verified v1.36.4+k3s1 (`4dedb15b`), Go 1.26.7; `--version` ran successfully |
| K3s kernel compatibility | Failed | `doas /usr/local/bin/k3s check-config` returned exit `4`; three required options missing |
| Replacement kernel source build | In progress | Pinned Linux 7.1.5 build route present; final artifacts, guest boot and runtime checks unverified |
| Optional built-kernel launcher | Local validation covered | Three-file input and artifact/configuration guards tested; replacement-kernel boot pending |
| Air-gap archive | Staged and verified | Official archive checked inside the guest; size `176533504` bytes |
| Smoke manifest | Parsed offline | Digest-pinned BusyBox HTTP workload prepared; not applied |
| K3s service, Ready node and Pods | Not verified | No running cluster or test workload |
| Android reboot and power loss | Not tested | No startup or power-loss recovery claim |
| Second Xperia | Not provisioned | No second-node or cross-phone network evidence |
| Business workloads | Absent | Reception remains documentation only; no business application or data transferred |

## Current Kubernetes blocker

The running kernel lacks:

- `CONFIG_IP_NF_TARGET_REJECT`
- `CONFIG_NETFILTER_XT_MATCH_MULTIPORT`
- `CONFIG_NETFILTER_XT_MATCH_STATISTIC`

The extraction preparer's initial feature gate passes, but it does not test the complete set
required by K3s. A replacement kernel must pass the runtime configuration check before cluster
readiness can be evaluated. Running `k3s --version` establishes binary execution only.

The current 1024 MiB guest allocation also remains below the documented K3s server minimum of
2 GB RAM. Baseline requirements exclude workload resources. See
[K3s requirements](https://docs.k3s.io/installation/requirements).

## Storage and recovery measurements

The cloud root initially occupied a 156.6 MiB filesystem. Manual partition expansion preserved
partition 2's starting sector 2048 and the EFI partition. Updating the partition view and growing
ext4 produced a 3.7 GiB root filesystem. After K3s extracted approximately 236 MiB of assets,
the recorded usage was 511.9 MiB with approximately 3.1 GiB available.

During an actual ADB transport interruption, the QEMU guest continued running and guest SSH worked
again after the connection recovered. This validates that observed management-transport event.
It does not test Android reboot, power loss, prolonged screen-off operation or guest network loss.

Two separate screen-off observations were taken 341 seconds apart. The guest boot ID and Android
last-wake/last-sleep timestamps were unchanged; Android's reported sleep duration increased from
approximately 44 to 50 minutes. Both samples reported 100% battery and 35.5 °C. These samples
establish guest continuity at the measured points, not Kubernetes availability or sustained
service performance throughout the interval.

The staged air-gap archive matched SHA-256
`d84268705e70019d76f4ef1c27cbb9d0bf480486e1d216103ebc732cfbd35bbb` inside the guest.
Container-runtime import, smoke-manifest application and an HTTP response remain unverified.

## Earlier boot route

The Alpine Virtual 3.24.2 ISO with Linux 6.18.52 reached OpenRC during an earlier two-vCPU attempt,
but no usable login was established through that route. Boot took approximately seven minutes;
hardware-driver loading did not complete within the observed 22-minute run. The cloud image with
the standalone kernel supersedes that route for the working guest. The ISO installer remains
unverified.

## Safeguard and preparation checks

The disk and SSH checker code was exercised in Termux against temporary fixtures:

| Check | Exit code | Expected result |
|---|---|---|
| Pristine qcow2 in the ISO launcher | `0` | Accept installation-media boot |
| qcow2 with allocated data in the ISO launcher | `1` | Reject installation-media boot |
| Dedicated SSH process and listener | `0` | Accept the existing management service |
| Unrelated live PID | `1` | Reject reuse; no process killed |

Cloud preparation tests cover public-key and hostname validation, private-key rejection,
checksum failures, cache reuse, resumed downloads and seed contents. Kernel preparation tests
cover hashes, ARM64 format, embedded configuration, extraction boundaries and preservation of
conflicting existing files. These tests use temporary local fixtures and do not boot a guest.

Build-configuration tests exercise the resolved configuration gate: all eleven network additions
must be built in, existing direct-boot requirements must remain enabled, and the release suffix
must be fixed. They do not compile Linux or establish that the resulting kernel will boot.

Launcher tests cover the optional built-kernel directory and artifact/configuration validation
before side effects. They do not execute a real QEMU boot.

## Reproducible local checks

Run from the repository root:

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

The 28 unit tests have passed locally: ten cloud-preparation tests, nine kernel-extraction tests,
four build-configuration tests and five launcher tests. The remaining commands check shell syntax and tracked-file
whitespace without connecting to a phone. Raw logs, keys, downloaded artifacts and guest disks
remain outside Git. The extracted artifact hashes are verified; the replacement build's final
output, bitwise reproducibility and upstream attestation remain unverified.

## Remaining acceptance criteria

1. Complete and verify the replacement build, validate its guest boot and rerun K3s configuration checks.
2. Establish adequate guest resources, start K3s and verify a Ready node and test Pod.
3. Reproduce the manual guest changes and verify a repeat boot of the completed configuration.
4. Provision the second Xperia, validate guest and pod networking, and join it as a K3s agent.
5. Measure Android reboot, power-loss, extended screen-off and network-recovery behavior.

Both Xperia nodes and their workload connectivity must be verified to complete the two-phone
objective. The management laptop remains outside the Kubernetes node topology.
