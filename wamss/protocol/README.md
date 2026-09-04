# Whick device ↔ CC protocol (shared)

고객 runtime (`agent`, `monitor`, UAB bootstrap) 공용.

- SSOT: [docs/DEVICE-CC-PROTOCOL.md](../docs/DEVICE-CC-PROTOCOL.md)
- `envelope.mjs` — 메시지 래퍼
- `cc-client.mjs` — fetch + Bearer + envelope POST
- `bootstrap-client.mjs` — UAB `/install/*`
- `runtime-state.mjs` — agent/monitor 공유 토큰 (`runtime-state.json`)
- `install-credentials.mjs` — UAB register-product 후 `mb_id` · `hw_id_hash` (`install-credentials.json`)
