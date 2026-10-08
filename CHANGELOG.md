# Cognesia release notes

## v0.0.2 — Protected application preview

- Personal access key sign-in for the official viewer, APIs, downloads,
  WebSocket streams, and local research console.
- Configurable trusted HTTPS verification, with an explicit loopback exception
  for operator-managed development and manual customer-key issuance.
- Account/workspace binding, read/run scopes, 30-minute sessions, and bounded
  30-second revalidation. Missing configuration and failed verification deny access.
- ParaLimbo 0.1 model selection and compilation/validation commands, with
  separately versioned model provenance and release evidence.
- Provider chemistry runs without unrelated FlyWire-only input files; runtime
  provenance records optional optical inputs and stable package source hashes.
- [Access setup](docs/app-access.md) and [website accounts plan](docs/website-accounts-plan.md).

Website signup, self-service keys, public HTTPS hosting, and an administrator
usage panel remain planned. Local source modifications are not a trusted central
usage meter. Original code and documentation remain all rights reserved.
This preview does not establish improved biological prediction accuracy or
resolve the historical scientific validation failures.

## v0.0.1 — Initial public source release preparation

- Local Python workbench and interactive 3D browser interface.
- FlyWire and BANC source pathways with versioned model provenance.
- Visual stimuli, virtual electrodes, chemical fields and experiment timelines.
- Recorded signals, supported checkpoint branching and local session exports.
- Optional native macOS window.
- Public documentation and a GitHub Pages project page.

This version labels the initial public source release. It does not change model
schema identifiers or imply that previous scientific validation failures have
been resolved. See `REPORT.md` and `LIMITATIONS.md` for the existing evidence.
Downloaded datasets, recordings, checkpoints, compiled models and the local
Python environment are not distributed. No publication date is claimed until
the repository and release are actually published.
