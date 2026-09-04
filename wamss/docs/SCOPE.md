# 고객 뮤직서버 — 제품 범위 (SSOT)

**갱신:** 2026-06-08  
**격리:** [ISOLATION.md](ISOLATION.md) — `5_site` · `2_control_center` **미수정** · `3_product` **복사본만**  
**한 줄:** Whick 솔루션 = **Ubuntu 26.04 + Docker runtime** — 고객에게 **하나의 가전 OS**처럼 제공.

---

## 1. 제품 정체성

| 고객이 보는 것 | 실제 |
|----------------|------|
| Whick 뮤직서버 | Ubuntu 26.04 + Whick runtime |
| 스마트폰 리모컨 | whick.org **앱/웹** → agent |
| 「Whick이 설치 중」 | UAB USB (나중) |

**포함:** Linux · Docker · 재생 · DAC · 관제 agent · (기본) 로컬 AI e2b  
**미포함:** whick.org · 그누보드 · ERP · 본사 Hermes/엘마

---

## 2. runtime 구성 (SSD `/opt/whick/runtime/`)

| 서비스 | 컨테이너 | 1차 | 체험 대응 |
|--------|----------|-----|-----------|
| **whick-agent** | `agent/` | ✅ 필수 | `music-server/agent` · `remote_cmd` · CC heartbeat |
| **whick-audio** | `audio/` | ✅ 필수 | `whick-room-sweep` 재생 경로 → **CamillaDSP/ALSA** |
| **whick-library** | `library/` | ⏳ TBD | 로컬 FLAC · Navidrome 또는 경량 |
| **whick-monitor** | `monitor/` | ✅ 1차 | 관제담당 L1 · CC snapshot · library job |
| **whick-local-ai** | `local-ai/` | ⏳ TBD | e2b CPU (CUSTOMER-INSTALL-PLAN §6) |
| **whick-updater** | `updater/` | ✅ 필수 | CC agent command · OTA |
| **whick-ai-agent** | — | ❌ 옵션 | E4B / Gemini Flash · 별도 가이드 |

---

## 3. 체험(5_site)에서 **가져올** 기능

| 체험 | 제품 이식 | 비고 |
|------|-----------|------|
| 공간음향 sync · `remote_cmd` | agent + CC/API | 브라우저 bridge ❌ |
| 스마트폰 리모컨 UI | whick.org **또는** 전용 앱 → agent | [DEVICE-HOUSEHOLD-REMOTE.md](../../install/DEVICE-HOUSEHOLD-REMOTE.md) |
| Web Audio EQ / PEQ | **CamillaDSP** yaml | `trial-player` DSP 탭 로직 참고 |
| 로컬 FLAC 재생 | agent + library | 체험 sample-audio 경로 대신 고객 NAS/SSD |
| YouTube 연동 | agent · **Gmail 1대/서버** | [YOUTUBE-CONNECT-POLICY.md](../../docs/YOUTUBE-CONNECT-POLICY.md) |
| AI 검색 (Ollama) | local-ai e2b | whick.org PHP ❌ |
| VIP/커뮤니티 | ❌ | whick.org only |

---

## 4. 체험에서 **가져오지 않을** 것

- 그누보드 · PHP 테마 · `trial.php` / `trial-player.php`
- `ajax.whick_trial.php` (회원 세션 JSON) → **device_id + CC** 로 대체
- PC 브라우저 스피커 재생 · `whick-trial-remote-bridge.js`
- whick.org 중앙 **yt-dlp** 프록시 → **미니PC 로컬**
- 엘마 · Hermes · FAQ PHP

---

## 5. OS · 플랫폼

| 항목 | 값 |
|------|-----|
| Host OS | **Ubuntu Server 26.04 LTS** |
| Orchestration | **Docker Compose v2** |
| 설치 | UAB USB (④단계 · 본 scope ①②③ 후) |
| HW 바인딩 | [LICENSE-HW-BINDING.md](../../install/LICENSE-HW-BINDING.md) |
| YouTube | Gmail 1 · Testing OAuth |

---

## 6. 외부 연동

| 시스템 | 방향 | 용도 |
|--------|------|------|
| **통합관제** | agent outbound HTTPS | heartbeat · attest · OTA · remote |
| **whick.org** | 스마트폰 → CC/agent | 리모컨 · owner/remote · (선택) 계정 |
| **ERP** | CC 경유 | entitlement · 주문 (agent 직접 ❌) |

---

## 7. 1차 MVP (PoC) 범위

**목표:** dev 미니PC 1대에서 **스마트폰으로 재생·일시정지·볼륨** + CC online.

- [ ] `compose.yaml` · agent · audio(Camilla)
- [ ] CC `/agent/register` · heartbeat
- [ ] `remote_cmd` play/pause/volume (체험 프로토콜)
- [ ] 로컬 FLAC 1곡 재생
- [ ] HW attest stub

**MVP 이후:** library · YouTube on device · spatial 측정 · local-ai e2b · claim wizard

---

## 8. 의사결정 보류

| 항목 | 선택지 |
|------|--------|
| library | Navidrome vs 경량 스캐너 |
| 스마트폰 UI | whick.org PWA vs 별도 앱 |
| LAN API | agent :port vs CC relay only |
