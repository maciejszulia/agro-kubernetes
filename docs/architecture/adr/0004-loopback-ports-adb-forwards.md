# ADR 0004: Loopback-only ports behind ADB forwards

## Status

Accepted (commit `d695b19`).

## Context

Termux SSH, the guest console, guest SSH and the future Kubernetes API must not be reachable from any phone network interface. The management host is connected to phone 1 over USB.

## Decision

Termux SSH binds `127.0.0.1:8022` with password and keyboard-interactive authentication disabled. QEMU forwards bind phone loopback (`127.0.0.1:10022`, `16443`, `10080`). The management host reaches them only through device-specific ADB forwards (18022, 18023, 18024, 16443, 18080). The wrappers `xa2-ssh` and `xa2-guest-ssh` use a dedicated Ed25519 key, `IdentitiesOnly=yes`, `BatchMode=yes` and `StrictHostKeyChecking=yes`.

## Consequences

- Positive: no lab service listens on a phone network interface.
- Positive: QEMU and guest SSH survived an actual ADB transport loss; forwards are recreated after reconnecting.
- Negative: management depends on USB and ADB; there is no remote access path.
- Negative: a forwarded API port gives no cross-node routing; two-node networking needs another design.
- Negative: all launchers share the same ports, so only one guest may run per phone.

## Evidence

- `scripts/termux-access.sh`: `ListenAddress 127.0.0.1`, `PasswordAuthentication no`, `KbdInteractiveAuthentication no`.
- `scripts/termux-kernel-start.sh`: `hostfwd=tcp:127.0.0.1:10022-:22` and the other forwards.
- `scripts/xa2-ssh`, `scripts/xa2-guest-ssh`.
- `docs/runbook.md`, "Port mappings and recovery".
