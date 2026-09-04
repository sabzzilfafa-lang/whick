# Whick Software

**Whick** builds free, source-first software for music lovers and creators.

## Products

| Product | Status | Source | Releases |
|---|---|---|---|
| **WAMSS** (Whick AI Music Server Solution) | Available | [`wamss/`](wamss/) | [`wamss-v*` tags](https://github.com/sabzzilfafa-lang/whick/releases) |
| **Suno Helper** | In final development | [`suno-helper/`](suno-helper/) | coming soon |

## Downloads

Official installers are distributed at **https://whick.org** — free direct download, no account required for download.

- **WAMSS**: wired LAN install USB image (x86-64 mini PCs) — verify the SHA-256 checksum on the download page
- **Suno Helper**: to be published on release

## Repository layout

```
whick/
├── wamss/          # WAMSS — self-hosted hi-fi music server
│   ├── install/    # install USB builder
│   ├── agent/      # device agent (registration, OTA, diagnostics)
│   ├── remote/     # remote web UI + streaming API
│   └── ...
├── suno-helper/    # Suno Helper — creator automation (in development)
├── LICENSE
└── SECURITY.md
```

## Source philosophy

Source-first — read what you run. See [LICENSE](LICENSE): free personal use, study and modification for personal use. Commercial resale or redistribution of modified builds requires written permission.

## Support

- Issues: https://github.com/sabzzilfafa-lang/whick/issues (label: `wamss` / `suno-helper`)
- Manual: https://whick.org/manual.html
- Site: https://whick.org