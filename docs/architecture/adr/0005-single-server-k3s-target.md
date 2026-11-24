# ADR 0005: One K3s server with SQLite and one agent

## Status

Proposed (target topology in `docs/architecture.md`, commit `d695b19`; not deployed).

## Context

The lab has two phones that can host guests. Both Kubernetes nodes must run on the phones; the T470p stays a management host. K3s embedded-etcd high availability needs at least three servers.

## Decision

The target cluster has one K3s server with the default SQLite datastore on phone 1 and one K3s agent on phone 2. The first test workload is `manifests/smoke.yaml`: a non-root BusyBox HTTP Deployment in namespace `agro-lab` with NodePort 30080, image pinned by digest from the official air-gap archive.

## Consequences

- Positive: the smallest topology that uses both phones as nodes.
- Negative: the server is a single control-plane failure domain.
- Negative: the target depends on an unresolved cross-phone guest network and on a compatible kernel.
- The reception panel stays a future workload specification (`docs/reception-target.md`); business data stays off the phones.

## Evidence

- `docs/architecture.md`, "Current system and target topology" and "Networking and failure domains".
- `manifests/smoke.yaml`.
- `docs/verification.md`, rows "Smoke manifest" and "K3s service, Ready node and Pods".
