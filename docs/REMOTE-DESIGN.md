# Whick Remote — 제품 리모컨 설계 (SSOT: v4)

**UI SSOT:** `packages/remote/index.html` (+ `js/remote_api.js`)  
**포털 (로그인·장비 선택):** `packages/remote-portal/` · `remote.whick.org` — [REMOTE-PORTAL.md](REMOTE-PORTAL.md)  
**원본 프로토타입(참고):** `/data/whick-ai/8_pds/_archive/product-prototypes/`  
**서버 SSOT:** `remote/api/music_api.py`

---

## 1. 역할

| | |
|--|--|
| **리모컨 (폰 PWA)** | **유일한 조작 UI** — 재생·라이브러리·공간음향·DSP·검색 (`packages/remote/`) · **LAN** `http://{IP}/` 또는 포털 `remote.whick.org` |
| **뮤직서버** | 미니PC FastAPI `:8080`(+`:80`) — REST/WS + **LAN 게스트용 리모컨 UI 서빙** |
| **재생 엔진** | MPD → CamillaDSP → DAC/AMP → 스피커 (로컬 FLAC **· 라디오 스트림** 동일 경로) |

**원칙:** 설치·OTA·관제는 agent/monitor. 조작은 **모바일 리모컨 → LAN/터널 → player**. 같은 공유기에서는 계정 없이 `http://{lan_ip}/` 로 게스트 리모컨.

체험 UI는 별도 SSOT이며 제품으로 복사·동기화하지 않는다.

---

## 2. 화면 (v4)

| # | 드로어 / 탭 | MVP API | 후순위 |
|---|-------------|---------|--------|
| 1 | 홈 · Now Playing | `state` WS · **`spectrum` WS** | VU/EQ = 미니PC FFT |
| 2 | 재생 전체화면 | transport WS | |
| 3 | 라이브러리 — 전체/아티스트/앨범 | REST `/api/tracks` … | |
| 4 | 즐겨찾기 | `/api/favorites` | |
| 5 | 재생 이력 | `/api/history` | |
| 6 | AI 검색 | `/api/ai-search` | Ollama on device |
| 7 | 라디오 | `/api/radio` · WS `play_radio` | **미니PC MPD** 스트림 → CamillaDSP (폰은 리모컨만) |
| 8 | **공간음향 마법사** | WS `spatial_*` + `/api/dsp/room-correction` | 폰 마이크 · 서버 스윕 |
| 9 | DSP · 라이브러리 · **스트리밍** | `/api/dsp/*` · `/api/library/*` · **`/api/streaming/*`** | Spotify Connect · Tidal device code — [EXTERNAL-PROVIDERS-DESIGN.md](EXTERNAL-PROVIDERS-DESIGN.md) |

**2차:** Spotify · Tidal만 (YouTube · Qobuz 제외) — [REMOTE-PHASE1-SCOPE.md](REMOTE-PHASE1-SCOPE.md)

---

## 3. 연결 (`WhickAPI`)

```
LAN  (192.168.x / 10.x / 172.16–31.x):
  HTTP  http://{host}:8080
  WS    ws://{host}:8080/ws

외부 (Cloudflare Tunnel):
  HTTP  https://{host}
  WS    wss://{host}/ws
```

- 서버 주소: `localStorage.whick_server` (설정 화면)
- **Wi-Fi ↔ LTE:** `WhickAPI` — **듀얼 링크** (LAN + 터널 동시 유지) · 고객 `connectMode` 로 주 경로 선택 · 끊김 시 0초 failover
- 포털: `whick_device_ep_{id}` — LAN·터널 프로필 localStorage · CC `/remote/devices` 갱신
- `USE_REAL_API` — 개발 시 mock / 실서버 전환 (배포 PWA는 항상 real)

### 3.1 듀얼 링크 (v4.1)

| 링크 | 유지 | 용도 |
|------|------|------|
| **터널** (`tunnel_host`) | 상시 | LTE·외부 · 관제 경유 |
| **LAN** (`lan_ip`) | Wi-Fi 존에서 추가 | 공유기 직접 · 저지연 |

- **주 연결(primary):** `connectMode` — `auto`(Wi-Fi 우선→터널) · `lan` · `tunnel`
- **대기(standby):** 다른 링크도 WebSocket 유지 — primary 끊기면 즉시 전환
- **상태 동기화:** primary 전환·재연결 시 `GET /api/state` 로 `stateCache` 갱신 (standby WS 초기 스냅샷은 무시)
- **UI:** `connected` / `primary_changed` / `disconnected`(전 링크 down 시만)

**인증 (1차):** `Authorization: Bearer {device_token}` · WS `?token=` — CC meta `remote_device_token` · player `/var/lib/whick/remote-device-token`

---

## 4. WebSocket

### 서버 → 클라이언트 (`event: "state"`)

```json
{
  "event": "state",
  "source": "library",
  "playing": true,
  "track_id": 42,
  "radio_station_id": null,
  "title": "Clair de Lune",
  "artist": "Debussy",
  "album": "Suite Bergamasque",
  "duration": 352,
  "position": 120,
  "volume": 70,
  "shuffle": false,
  "repeat": "none",
  "quality": "24/96 FLAC",
  "queue": [42, 7, 9],
  "library_total": 271
}
```

`source`: `library` | `radio` | `idle`  
`repeat`: `none` | `one` | `all`

### 서버 → 클라이언트 (`event: "spectrum"`)

MPD fifo PCM → 미니PC FFT(24밴드) → LAN/터널 동일 WS.

```json
{
  "event": "spectrum",
  "source": "library",
  "playing": true,
  "band_count": 24,
  "bands": [0.05, 0.12, 0.34, "..."]
}
```

재생 중 ~15Hz 푸시. 정지 시 레벨 decay.

### 클라이언트 → 서버

| cmd | fields |
|-----|--------|
| `play` | `track_id?`, `output?` |
| `pause` | `output?` |
| `toggle` | `output?` |
| `next` / `prev` | `output?` |
| `seek` | `position` (초), `output?` |
| `volume` | `value` 0–100, `output?` |
| `shuffle` | `value` bool, `output?` |
| `repeat` | `value` `none`\|`one`\|`all` 또는 `toggle`, `output?` |
| `add_to_queue` | `track_id`, `output?` |
| `play_queue` | `track_ids`, `index`, `output?` |
| `play_album` | `album`, `artist?`, `output?` |
| `play_radio` | `station_id`, `output?` — `server`(기본) MPD 재생 · `mobile` 상태만 |
| `stop_radio` | 라디오 중지 |

모든 WS 명령에 `output` 필드(선택): `server`(기본) · `mobile`. 클라이언트 `localStorage` `whick_remote_output`로 전역 설정.

### 재생 출력 (전역)

| 모드 | 동작 |
|------|------|
| **server** (기본) | 미니PC MPD → CamillaDSP → DAC/AMP/스피커. 내장 FLAC · 라디오 · 플레이리스트 등 **모든 소스** |
| **mobile** | 미니PC는 재생 상태·큐만 관리(MPD 미사용). 스트림을 REST로 제공 → PWA `Audio()` 재생. 공유기 LAN 또는 터널 동일 API |

설정 UI: PWA 설정 → 「재생 출력」(id `sec-speaker`).

---

## 5. REST

| Method | Path | 용도 |
|--------|------|------|
| GET | `/api/state` | WS 끊김 fallback |
| GET | `/api/playback/now` | 모바일 출력용 현재 재생 + `stream_url` (library · radio) |
| GET | `/api/tracks?page&sort&per_page` | 전체 목록 |
| GET | `/api/artists` | |
| GET | `/api/albums` | |
| GET | `/api/artists/{name}/tracks` | |
| GET | `/api/albums/{name}/tracks` | |
| GET | `/api/search?q=` | 키워드 |
| GET | `/api/ai-search?q=` | Ollama → 키워드 → DB |
| GET | `/api/favorites` | |
| POST | `/api/favorites/{track_id}` | |
| DELETE | `/api/favorites/{track_id}` | |
| GET | `/api/history?limit=50` | 최근 재생 |
| GET | `/api/radio` | 방송국 목록 |
| GET | `/api/radio/{id}/play` | 서버 MPD 재생 · `{ ok, name, station_id, playback: "server" }` |
| GET | `/api/radio/{id}/stream` | 모바일 출력용 `{ stream_url, name, station_id }` (MPD 미시작) |
| GET | `/api/tracks/{id}/stream` | 모바일 출력용 로컬 FLAC/음원 파일 스트림 |
| GET | `/health` | |

트랙 JSON 필드: `track_id`, `title`, `artist`, `album`, `duration_sec`, `bit_depth`, `sample_rate`, `format`

---

## 6. 파일 배치

```
3_product/
├── packages/remote/             # UI SSOT (v4)
│   ├── index.html
│   └── js/remote_api.js
├── remote/api/
│   ├── music_api.py
│   ├── init.sql
│   └── requirements.txt
└── (참고 프로토타입 → /data/whick-ai/8_pds/_archive/product-prototypes/)
```

---

## 7. 체험 대비 변경 요약

| 체험 | v4 제품 |
|------|---------|
| `spatial_remote_cmd` JSON 파일 | WS 명령 |
| PC 브라우저 bridge | 서버 MPD |
| 폰 `<audio>` 라디오 | **미니PC MPD** → CamillaDSP → AMP |
| `mb_no` 세션 | `device_id` + token (예정) |
| whick.org PHP AI | `/api/ai-search` on device |

---

## 8. 구현 순서

1. ✅ API·`remote_api.js` v4 계약 정렬  
2. PoC: `docker compose` + MPD + `music_api` + v4 `USE_REAL_API=true`  
3. `packages/remote/index.html` PWA manifest  
4. agent가 `music_api` 내장 또는 reverse proxy  
5. spatial/DSP/YouTube — agent·Camilla 스펙 후 설정 탭 연동  
6. **플레이리스트 공유** (외부 친구 · 게스트) — [PLAYLIST-SHARE.md](PLAYLIST-SHARE.md)
