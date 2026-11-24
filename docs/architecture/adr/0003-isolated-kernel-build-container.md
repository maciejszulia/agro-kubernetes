# ADR 0003: Kernel build in an isolated container

## Status

Accepted; build in progress as of 2026-09-25 (commit `d695b19`).

## Context

`k3s check-config` exits `4` on the extracted Podroid kernel because three netfilter options are missing. A replacement ARM64 kernel must keep the working baseline configuration, add the missing options and be built on the x86-64 management host without trusting the build environment with the network or the host.

## Decision

`scripts/build-kernel.sh` merges `config/k3s-kernel.config` (eleven built-in network options and the `-agro1` release suffix) into the extracted baseline, resolves it with `olddefconfig` and validates the result. It compiles inside the `docker/kernel-builder.Dockerfile` image with `--network none`, `--cpus 3`, `--memory 4g`, `--cap-drop ALL`, `--security-opt no-new-privileges` and `--read-only`. It writes `Image`, `kernel.config`, `System.map` and `build-metadata.json`. The launcher accepts the three-file output directory and checks release `7.1.5-agro1`, hashes and required options before boot.

## Consequences

- Positive: the compiler has no network and limited resources; source download happens before, with hash checks.
- Positive: the launcher refuses a kernel whose metadata or options do not match.
- Negative: the build needs Docker and host capacity; it is not reproducible bit for bit.
- Negative: the replacement kernel has not yet booted or passed `k3s check-config`.

## Evidence

- `scripts/build-kernel.sh`, the `docker run` call with `--network none` and resource limits.
- `config/k3s-kernel.config`.
- `docs/runbook.md`, "Build the replacement kernel".
- `tests/test_build_kernel.py`, `tests/test_termux_kernel_start.py`.
