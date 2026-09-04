# whick-audio

CamillaDSP · ALSA → DAC (**Phase 1: HTTP stub**).

현재 `src/server.mjs` — play/pause/stop/volume 상태만 유지. agent `commands/poll`이 여기로 POST.

## Endpoints

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | 헬스 |
| GET | `/status` | 재생 상태 |
| POST | `/play` | `{ track, path, title }` |
| POST | `/pause` | |
| POST | `/stop` | |
| POST | `/volume` | `{ volume }` 0–100 |

room PEQ → **CamillaDSP yaml** 이식 예정.
