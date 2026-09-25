# Reception panel: future workload

The reception panel is a possible later workload for the phone cluster. This document records its
runtime and packaging requirements; it is not a deployment procedure. No panel image, running
service, existing database, guest information or production credential has been transferred to
the phones.

## Source baseline

The requirements below derive from read-only source inspection of `agrocamping-recepcja`, reference
commit `197aa4985d0497ff73914b100f877f77734c5237`, on 2026-09-25. Paths in this document are relative
to that application's repository. Container builds, ARM64 execution and Kubernetes deployment
remain unverified.

## Runtime components

| Component | Requirement | Source |
|---|---|---|
| Backend | Compiled TypeScript on Node 22, Express and Prisma 6 | `backend/package.json`, `backend/src/utils/db.ts` |
| Frontend | Astro static build; Node 22 must be at least 22.12.0 for the recorded toolchain | `frontend/package.json`, `frontend/package-lock.json` |
| Panel gateway | Serve static assets, handle authentication and sessions, and forward API traffic | `scripts/panel-gateway.mjs` |
| Backend connection | Gateway permits only `127.0.0.1` as the backend host | `scripts/panel-gateway.mjs`, `createPanelGateway` |

Astro preview alone does not provide the panel gateway. A future deployment must preserve the
gateway's loopback backend boundary. Colocating gateway and backend in one Pod is a candidate
layout, not a tested Kubernetes configuration.

## Persistent state

The backend uses SQLite with WAL and accepts the runtime override `RECEPCJA_DATABASE_URL`.
Persistent storage must cover the database directory, including WAL and shared-memory sidecar
files, rather than a single database file. See `backend/src/utils/db.ts`.

Gateway pairing, sessions, rate limits and authentication audit state use
`RECEPCJA_PANEL_STATE_DIR`. Import checkpoints and local payment-method configuration are separate
state files. See `scripts/panel-gateway.mjs` and `scripts/deploy-release.sh`.

The initial workload constraint is one reception replica with isolated persistent storage.
Local SQLite does not provide automatic cross-phone database failover. Storage recovery and
resource requirements on an emulated Xperia remain unmeasured.

## Packaging and validation gaps

- **Backend build context:** the build invokes `scripts/write-release-label.sh`, but the existing
  backend Dockerfile does not copy it and `.dockerignore` excludes it. The existing container files
  need independent build validation before reuse. Sources: `backend/package.json`,
  `backend/Dockerfile`, `.dockerignore`.
- **Frontend serving:** the existing frontend container starts Astro preview. Kubernetes packaging
  must include the actual gateway and its state. Sources: `frontend/Dockerfile`,
  `scripts/panel-gateway.mjs`.
- **ARM64 artifacts:** build and test native dependencies and the generated Prisma client for the
  target architecture in an isolated context. Host `node_modules` is not a deployment artifact.
  Sources: `backend/Dockerfile`, `backend/prisma/schema.prisma`.
- **Database initialization:** create a fresh lab database through the existing migrations. Startup
  checks migration history, and the Prisma schema contains a fixed migration database URL; the
  application's runtime override does not redirect Prisma CLI migrations. Sources:
  `backend/src/services/startup-integrity.ts`, `backend/prisma/schema.prisma`,
  `scripts/deploy-release.sh`, `prepare_database_schema`.
- **Integration isolation:** use synthetic data and lab-only credentials with external integrations
  disabled. The website booking and occupancy runners do not start when
  `WEBSITE_BOOKING_CONFIG_FILE` is unset; other integrations need their own isolation checks.
  Sources: `backend/src/services/website-booking-sync-runner.ts`,
  `backend/src/services/website-occupancy-runner.ts`.

The first phone's native Termux control plane passes its readiness checks and the guest worker
is Ready. The smoke Pod has served exact HTTP responses, but later requests timed out despite
readiness. CoreDNS remains 0/1 Ready; stable HTTP, DNS and policy behavior are unverified.
Reception deployment still requires sustained availability, adequate resources, persistent
storage and recovery tests. No business workload is present on
either phone.
