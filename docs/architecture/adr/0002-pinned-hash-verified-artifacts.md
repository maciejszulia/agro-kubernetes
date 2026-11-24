# ADR 0002: Pinned, hash-verified artifacts

## Status

Accepted (commit `d695b19`).

## Context

The lab downloads a cloud image, a kernel source archive and an APK that carries a prebuilt kernel. The APK comes from a third-party release and must never be installed on Android. A changed upstream file must not reach the phone unnoticed.

## Decision

Every download is pinned to one version and one hash, and the scripts check the hash before they use the file:

- `scripts/prepare-cloud.py`: Alpine `generic_alpine-3.24.1-aarch64-uefi-tiny-r0.qcow2`, SHA-512 constant `SHA512`.
- `scripts/prepare-kernel.py`: Podroid v1.2.9 APK and the extracted `Image`, SHA-256 constants `APK_SHA256` and `IMAGE_SHA256`; the APK is opened as an archive and only the kernel payload is extracted.
- `scripts/build-kernel.sh`: Linux 7.1.5 source archive and the baseline configuration, checked with `sha256sum -c`.
- `docker/kernel-builder.Dockerfile`: `debian:bookworm-slim` pinned by digest.
- `scripts/termux-kernel-start.sh`: checks the kernel and base-image hashes before it creates an overlay or starts QEMU.

## Consequences

- Positive: a changed or corrupted download stops the run before side effects.
- Positive: the APK is never installed or executed.
- Negative: every version upgrade needs new constants in code and in the tests.
- Negative: hash checks prove integrity against the pin, not a reproducible build or an upstream attestation (stated in `docs/architecture.md`).

## Evidence

- `scripts/prepare-cloud.py` (line with `SHA512 =`), `scripts/prepare-kernel.py` (`APK_SHA256`, `IMAGE_SHA256`), `scripts/build-kernel.sh` (`sha256sum -c`), `docker/kernel-builder.Dockerfile` (`FROM ...@sha256:...`).
- `tests/test_prepare_cloud.py`, `tests/test_prepare_kernel.py`.
