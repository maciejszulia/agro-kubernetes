# ADR 0001: QEMU full-system guest on unrooted Android

## Status

Accepted (commit `d695b19`).

## Context

K3s needs a Linux kernel with namespaces, pure cgroup v2 and netfilter features, and it needs root. The phones run Android 9 with a locked bootloader and must stay unrooted. Termux runs in an unprivileged app sandbox; the Android host exposes mixed cgroup v1/v2 mounts. PRoot gives no real root, namespaces or cgroup isolation. K3s rootless mode needs delegated pure cgroup v2 and does not support multi-node rootless clusters.

## Decision

Each phone runs QEMU full-system emulation (`qemu-system-aarch64`, machine `virt`, GICv3, multithreaded TCG) inside Termux. The guest is an Alpine 3.24.1 ARM64 cloud image that boots directly from a separate kernel (`-kernel`). The guest disk is a qcow2 overlay in app-private storage; no phone partition is used.

## Consequences

- Positive: the guest has its own kernel, real root and pure cgroup v2 without rooting Android (verified on phone 1).
- Positive: a kernel can be replaced by passing another `Image`; Android stays untouched.
- Negative: TCG software emulation is slow; 2 vCPUs and 1024 MiB RAM are below the K3s server baseline.
- Negative: the guest kernel must carry every K3s requirement; the current kernel lacks three netfilter options.
- Negative: guest networking is QEMU user-mode NAT, so cross-phone pod networking is unresolved.

## Evidence

- `docs/architecture.md`, "Guest kernel boundary".
- `scripts/termux-kernel-start.sh`: `-cpu max,pauth-impdef=on -smp 2 -m 1024` and `-netdev user,...`.
- `docs/verification.md`, rows "Current boot" and "Cgroups".
