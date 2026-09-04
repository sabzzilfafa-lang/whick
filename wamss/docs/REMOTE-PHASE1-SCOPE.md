# Whick Remote — 1차 / 2차 개발 범위

**SSOT:** [REMOTE-DESIGN.md](REMOTE-DESIGN.md)

---

## 1차 (현재 — 미니PC 리모컨 MVP)

| 포함 | 설명 |
|------|------|
| 홈 · 재생 · 라이브러리 · AI검색 · 라디오 | v4 PWA + player `:8080` |
| 공간음향 · DSP · 스피커 L/R · 출력 셀렉트 | CamillaDSP · server/mobile |
| USB · incoming 검수 UI | robot-auditor 규칙 · **user_approved** import/delete |
| device_token | player 선택적 Bearer · WS `?token=` |
| remote.whick.org | 로그인 · 장비 · v4 embed |
| cc_device_members | owner + remote(3) 초대 API |

## 2차 (진행 중)

| 포함 | 설명 |
|------|------|
| **Spotify · Tidal** | 설정 UI · 연결 마법사 · `/api/streaming/*` — [EXTERNAL-PROVIDERS-DESIGN.md](EXTERNAL-PROVIDERS-DESIGN.md) |

| 제외 | 설명 |
|------|------|
| **유튜브 연결** | Google OAuth — 소비자 UX 부적합 |
| **Qobuz** | Phase 2 범위 외 |
| 플레이리스트 외부 공유 | [PLAYLIST-SHARE.md](PLAYLIST-SHARE.md) |
| 실폰 터널↔Wi-Fi E2E | QA · 수동 검증 |

`WHICK_PLAYER_EXTERNAL_PROVIDERS=1` 시 설정 탭 **스트리밍 연동** 노출.
