# remote — 고객 뮤직서버 리모컨 API

스마트폰 ↔ 미니PC `:8080` · v4 `remote_api.js` 계약 ([REMOTE-DESIGN.md](../docs/REMOTE-DESIGN.md))

| 하위 | 내용 |
|------|------|
| `api/` | **FastAPI** — WebSocket 재생 + REST 카탈로그 |
| `docker/` | MPD 설정 · entrypoint · 데모 시드 |
| `Dockerfile` | **whick-player** 컨테이너 (MPD + music_api) |

## Docker runtime (고객 SSD)

`compose.yaml` 서비스:

| 서비스 | 역할 | 포트 |
|--------|------|------|
| `player-db` | PostgreSQL 카탈로그 | 내부 5432 |
| `player` | MPD + FastAPI | **8080** (LAN 리모컨) |

```bash
cd /data/whick-ai_music_server/3_product
docker compose up -d --build player-db player
curl -s http://127.0.0.1:8080/health
curl -s http://127.0.0.1:8080/api/tracks | head
```

검증: `scripts/test-player-docker.sh`

PoC 재생: `WHICK_CAMILLA_ENABLED=1` 시 MPD **pipe → CamillaDSP** (Docker lab은 null sink). 실 DAC는 `WHICK_CAMILLA_ALSA_DEVICE`.

owner / remote 역할: [install/DEVICE-HOUSEHOLD-REMOTE.md](../../install/DEVICE-HOUSEHOLD-REMOTE.md)
