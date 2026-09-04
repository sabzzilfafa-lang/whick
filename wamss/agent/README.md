# whick-agent

미니PC 상주 — CC register · heartbeat · `commands/poll` · audio stub 연동.

## 역할

| 기능 | CC API | 주기 |
|------|--------|------|
| 등록 | `POST /agent/register` | 최초 1회 → `runtime-state.json` |
| heartbeat | `POST /agent/heartbeat` | 60s (CC 응답 기준) |
| remote_cmd | `GET /agent/commands/poll` | 5s |
| 재생 | `WHICK_AUDIO_URL` → `/play` `/pause` | 이벤트 |

**SSOT 프로토콜:** `../protocol/` · `../docs/DEVICE-CC-PROTOCOL.md`  
**체험 참고 (read-only):** `../../music-server/agent/agent.mjs`

## 로컬 dev

```bash
# CC API (8090) 기동 후
cd /data/whick-ai_music_server/3_product
cp .env.example .env
./scripts/dev-up.sh
docker compose logs -f agent monitor audio
```

## 고객 테스트 노트북 (Linux 미니PC 대용)

본사 CC API는 서버 `127.0.0.1:8090` 전용. 노트북에서는 **SSH 터널** 후 runtime 기동.

```bash
# 터미널 1 — 본사 서버 (터널 유지)
ssh -N -L 8090:127.0.0.1:8090 whick@ssh.whick.org

# 터미널 2 — 노트북
cd 3_product   # rsync/git로 복사한 경로
./scripts/laptop-test-setup.sh
```

관제 UI: **https://admin.whick.org/** (`control.whick.org` 는 DNS 없음)

`WHICK_AGENT_TOKEN` 없으면 agent가 자동 register → `/var/lib/whick/runtime-state.json` 저장 → monitor가 동일 토큰 사용.

## Install smoke (bootstrap)

```bash
node bootstrap/cli.mjs --cc http://127.0.0.1:8090/api/v1
```

## 환경변수

| 변수 | 설명 |
|------|------|
| `WHICK_CC_API_URL` | CC base (`…/api/v1`) |
| `WHICK_DEVICE_SERIAL` | install `hw_id_hash` (64hex). 미설정 시 `install-credentials.json` |
| `WHICK_OWNER_MB_ID` | 소유자 whick.org `mb_id` (register 필수). 미설정 시 install-credentials |
| `WHICK_AGENT_TOKEN` | 있으면 register 생략 |
| `WHICK_AUDIO_URL` | audio (host network 기본 `http://127.0.0.1:8787`) |
| `WHICK_PLAYER_URL` | player (host network 기본 `http://127.0.0.1:8080`) |
| `WHICK_STATE_PATH` | 공유 state (기본 `/var/lib/whick/runtime-state.json`) |

## 다음

- CamillaDSP/ALSA 실제 출력 (`audio/`)
- HW attest · policy sync
- LAN remote API (`remote/`)
