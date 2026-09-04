# Whick 외부 스트리밍 — Spotify · Tidal (SSOT)

**갱신:** 2026-06-22  
**UI:** `packages/remote/index.html` · `js/whick-streaming-wizard.js`  
**API:** `remote/api/streaming_providers.py` · `music_api.py`  
**범위:** Spotify · Tidal만 (YouTube · Qobuz 제외)

---

## 1. 원칙

| 항목 | 결정 |
|------|------|
| **재생 위치** | 미니PC headless 코어 → **CamillaDSP** → DAC (폰은 리모컨만) |
| **인증 UX** | 소비자에게 **단계별 안내** — ID/PW 직접 입력 없음 |
| **Spotify** | **Spotify Connect** (폰 Spotify 앱 → Whick 기기 선택) |
| **Tidal** | **Device code** (link.tidal.com + 화면 코드) |
| **계정** | 미니PC 1대당 **구독 계정 1개** / provider |
| **고객 입력** | Spotify/Tidal **유료 계정 인증만**. API 키·Client ID는 고객에게 받지 않음 |
| **플래그** | `WHICK_PLAYER_EXTERNAL_PROVIDERS=1` |

---

## 2. Spotify 연결 (소비자 UX)

```
① 리모컨 설정 → Spotify → 「연결 시작」
② 안내: "폰에서 Spotify 앱을 여세요"
③ Spotify → 기기 연결(Connect) → 「Whick Player」선택
④ 미니PC librespot 세션 저장 → 연결 완료
```

- **Premium** 구독 필요
- Whick 리모컨에 **비밀번호 입력 없음**
- librespot zeroconf + credential cache (`/var/lib/whick/providers/spotify/`)

---

## 3. Tidal 연결 (device code)

```
① 리모컨 설정 → Tidal → 「연결 시작」
② 화면에 코드 + link.tidal.com
③ Tidal 계정 로그인 → 코드 입력
④ 폴링 완료 → MPD → CamillaDSP 재생
```

- **HiFi / HiFi Plus** 구독 필요
- Tidal device flow client 설정은 **Whick 운영/제품 설정**이며, 고객에게 입력받지 않는다.
- **`WHICK_TIDAL_COUNTRY_CODE`**: Tidal **계정** 카탈로그 지역 (ISO, 예: `US`) — 미설정 시 `US`
- 한국 미공식 지원 등 지역 이슈는 사용자 계정·설정 범위 (Whick은 API·재생 경로만 제공)

---

## 4. API

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/streaming/status` | Spotify · Tidal 상태 |
| GET | `/api/streaming/search?q=` | Spotify · Tidal 검색 |
| POST | `/api/streaming/play` | 스트리밍 곡 재생 |
| POST | `/api/streaming/spotify/connect/start` | librespot 대기 모드 |
| POST | `/api/streaming/spotify/connect/complete` | Connect 완료 확인 |
| POST | `/api/streaming/spotify/oauth/start` | Web API PKCE 시작 |
| GET | `/api/streaming/spotify/oauth/callback` | OAuth redirect |
| GET | `/api/streaming/spotify/oauth/status` | Web API 토큰 상태 |
| POST | `/api/streaming/spotify/disconnect` | 연결 해제 |
| POST | `/api/streaming/tidal/connect/start` | device code 발급 |
| GET | `/api/streaming/tidal/connect/poll` | 승인 폴링 |
| POST | `/api/streaming/tidal/disconnect` | 연결 해제 |

**AI 검색** `GET /api/ai-search?q=` — `local` · `spotify` · `tidal` 쿼리 플래그로 통합 검색.

**WebSocket** `play_streaming_queue` · `play_streaming` — 리모컨 재생·큐.

`external_providers_enabled: false` 시 **503**.

---

## 5. 환경 변수

| 변수 | 설명 |
|------|------|
| `WHICK_PLAYER_EXTERNAL_PROVIDERS` | `1` = API · UI 활성 |
| `WHICK_PROVIDERS_DIR` | credential · state (기본 `/var/lib/whick/providers`) |
| `WHICK_LIBRESPOT_BIN` | librespot 경로 (없으면 Connect 대기만) |
| `WHICK_SPOTIFY_CLIENT_ID` | 시스템 운영자용 Web API PKCE (선택 · 고객 입력값 아님) |
| `WHICK_SPOTIFY_REDIRECT_URI` | OAuth callback (미니PC IP:8080) |
| `WHICK_STREAMING_LAB` | `1` = mock (CI). 실테스트 `0` |
| `WHICK_TIDAL_COUNTRY_CODE` | Tidal 계정 카탈로그 (기본 `US`) |
| `WHICK_TIDAL_CLIENT_ID` | 시스템 운영자용 Tidal device flow client (고객 입력값 아님) |

---

## 6. 오디오 경로 (MPD → CamillaDSP)

```
MPD play (FLAC · 라디오 · Tidal lab · …)
  → pipe: camilla-pipe.sh
  → ffmpeg s16le 44.1k → f32le 48k
  → camilladsp profile.yml
  → ALSA (WHICK_CAMILLA_ALSA_DEVICE) 또는 null sink (Docker lab)
```

| 변수 | 설명 |
|------|------|
| `WHICK_CAMILLA_ENABLED` | `1` = MPD pipe → Camilla (기본 `1`) |
| `WHICK_CAMILLA_PROFILE` | yaml 경로 |
| `WHICK_CAMILLA_ALSA_DEVICE` | 실 DAC (예: `default`, `hw:0,0`) |
| `WHICK_LIBRESPOT_AUTOSTART` | `1` + external providers 시 librespot zeroconf |

**API:** `GET /api/dsp/pipeline` — camilladsp · MPD 모드 · log tail

Spotify Web API 재생(lab)도 **MPD 경로**를 타면 CamillaDSP를 거칩니다.  
**Spotify Connect 재생**은 librespot → `librespot-camilla.sh` → CamillaDSP → DAC.

---

## 7. 집에서 실 테스트 (외부 노트북 · LAN)

### 7.1 compose / `.env`

```bash
WHICK_PLAYER_EXTERNAL_PROVIDERS=1
WHICK_STREAMING_LAB=0
WHICK_LIBRESPOT_AUTOSTART=1
WHICK_CAMILLA_ENABLED=1
WHICK_CAMILLA_ALSA_DEVICE=default   # 미니PC DAC 연결 시
WHICK_PLAYER_PORT_BIND=0.0.0.0:8080
# 아래 provider client 설정은 Whick 운영/제품 설정. 고객은 유료 계정 인증만 진행.
# WHICK_SPOTIFY_CLIENT_ID=<Whick 운영 앱>
# WHICK_SPOTIFY_REDIRECT_URI=http://<미니PC-IP>:8080/api/streaming/spotify/oauth/callback
# WHICK_TIDAL_CLIENT_ID=<Whick 운영 client>
# WHICK_TIDAL_COUNTRY_CODE=US
```

```bash
cd 3_product && docker compose build player && docker compose up -d player
```

### 7.2 Spotify (2단계)

1. 노트북 브라우저 → `http://<미니PC-IP>:8080` 리모컨 → **설정 → 스트리밍 연동 → Spotify**
2. **Connect**: 폰 Spotify → 기기 **Whick Player** 선택 → 연결 확인
3. **선택 Web API**: Whick 운영 앱 설정이 있는 경우에만 브라우저 OAuth 승인
4. AI 검색 → Spotify 칩 → 곡 재생 → `librespot-camilla.log` · DAC 확인

### 7.3 Tidal (선택)

Tidal 사용자는 link.tidal.com에서 **유료 계정 로그인 + 화면 코드 입력**으로 device code 연동. `WHICK_TIDAL_CLIENT_ID`는 Whick 운영/제품 설정이며 고객 입력값이 아니다. 재생 경로: MPD → camilla-pipe → DAC.

### 7.4 확인 API

| GET | 설명 |
|-----|------|
| `/api/streaming/status` | Connect · Web API · librespot |
| `/api/dsp/pipeline` | camilla-pipe · librespot 경로 |

### 7.5 OAuth Redirect (Spotify Dashboard)

Spotify Developer → 앱 → Redirect URIs에 **정확히**  
`http://<미니PC-LAN-IP>:8080/api/streaming/spotify/oauth/callback` 등록.
