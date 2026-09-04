# Security Policy

## Supported versions

We provide security fixes for the latest release published at https://whick.org.

## Reporting a vulnerability

Please do **not** open a public issue for security problems.

- Report to: **security@whick.org** (or via https://whick.org)
- Include: product and version, steps to reproduce, and impact.
- We aim to acknowledge reports within 72 hours.

## Scope

- WAMSS install USB / Whick OS, device agent, remote web UI and streaming API in this repository.
- Out of scope: the hosting infrastructure of whick.org.

## Design notes

- Customer mini PCs make no inbound ports available: all remote access goes through outbound tunnels.
- No accounts or telemetry are required for local music playback.
