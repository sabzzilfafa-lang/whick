# 초기 연동 단계 (1~4) vs 원격 단계 (5~)

고객 미니PC 설치는 **초기 연동(1~4)** 과 **원격 단계(5~)** 로 나뉩니다.  
**4번까지 완료**되어야 관제에서 고객·장비·회원번호가 한 세트로 잡히고, 그 다음 원격 설치·리모트가 가능합니다.

**오프라인 Wi-Fi 우선 흐름 (AP → 로컬 :8765 → CC 1~4):**  
[`docs/INSTALL-OFFLINE-WIFI-DESIGN.md`](../../../docs/INSTALL-OFFLINE-WIFI-DESIGN.md) (SSOT)

---

## 초기 연동 (반드시 준비 · 1~4)

| # | 단계 | 내용 | CC API | 장비(미니PC) | 상태 |
|---|------|------|--------|--------------|------|
| **1** | 설치 세션 | 임시 장비코드 `MUSIC-xxxx`, bootstrap 토큰 | `POST /install/sessions` | `whick-boot-connect.sh` | ✅ USB connect |
| **2** | HW 등록 | `hw_id_hash`(64자) + 지문, tier 분석 | `POST /install/hw-report` | 동일 | ✅ USB connect |
| **3** | 고객 바인딩 | whick.org 회원(`mb_id`) ↔ 세션·장비 · **auto-register** | `POST /install/auto-register` | 미니PC `try_auto_register()` | ✅ CC · ⏳ 실기 E2E |
| **4** | 회원번호 확정 | 구매 시 `pending_install` → **active**, `member_no` | `ensureDeviceMemberNo()` (register 내부) | 3번 성공 시 자동 | ✅ 세션 177 |

### 1~2와 3~4의 차이

- **1~2:** 네트워크만 되면 미니PC가 **혼자** CC에 접속 가능 (USB boot-connect).
- **3~4:** 고객 **whick.org 로그인**으로 본인 확인 후, CC가 장비·구매 계약(`member_no`)을 묶음.

### Phase 3~4 register 경로 (2026-06-20)

whick.org **사전 로그인**(같은 Wi-Fi) → IP 매칭 → 설치 메일 · 세션 `mb_id` 바인딩.

```
미니PC  hw-report / ap-ready (client IP)
    → bindInstallSessionFromSiteLogin
스마트폰  설치 도우미 접속 → mark_phone_seen
    → try_auto_register()
    → CC  POST /install/auto-register  (bootstrap · mb_id · 비밀번호 없음)
```

수동 `/api/register`(비밀번호) · `POST /install/register-product` — **레거시 fallback** (`/api/register-manual`).

**오프라인/현장 경로:** Phase 1~2는 **유선 LAN URL** 또는 **whick.org 고유 접속 주소** (가상 AP 폐기 · 무선은 VIP provision STA).

### 회원번호 두 종류

| 코드 | 예 | 단계 |
|------|-----|------|
| `device_code` | `MUSIC-7K3Q` | 1번 — 임시 설치 코드 |
| `member_no` | `msnt-2606180001` | 구매 시 pending → **4번 active** |

구매(`sync-purchase`) 시 CC에 `member_no`가 **설치대기**로 먼저 생깁니다.  
4번에서 `register-product`가 장비에 붙이면 관제 **고객관리**에서 active로 보입니다.

### 3번 UI·검증

- USB `boot-connect`: **bootstrap_token** 유지 (세션 12h)
- 스마트폰: `install.html` — **진행률만** (로그인·장비등록 버튼 없음)
- whick.org: **부팅 전** 사이트 로그인(필수) · IP 매칭으로 자동 등록

참고 구현: `boot-connect/whick-customer-setup.py` · `boot-connect/cc_client.py` · `templates/install.html`

---

## 내일 (2026-06-21 예정)

1. **USB** — `release-connect-usb.sh` 빌드·`test-connect-suite` PASS · 실USB 재구워 테스트
2. **설치 도우미** — `/api/status` 실시간 갱신 · auto-register → `register_done` **실기 E2E**
3. **원격 설치 5~** — `REMOTE-PHASE-SERVER.md` · progress PATCH · phases/*.sh · 관제 UI 연동

---

## 원격 단계 (5~ · 4번 이후)

| # | 단계 | CC 서버 | 장비(UAB) |
|---|------|---------|-----------|
| **5** | 본 설치 progress | ✅ consent · proceed · PATCH progress | ⏳ phases/*.sh |
| **6** | agent + heartbeat | ✅ (기존) | ⏳ 04_runtime.sh |
| **7** | 리모트·OTA | ✅ ops + updates/pending | ⏳ updater · apply_update handler |

상세 API: [`REMOTE-PHASE-SERVER.md`](REMOTE-PHASE-SERVER.md)

---

## 관제(admin.whick.org)에서 보이는 시점

| 관제 화면 | 1~2만 | 1~4 완료 | 5~7 완료 |
|-----------|-------|----------|----------|
| 설치 세션 / hw_id | ✅ | ✅ | ✅ |
| 고객 ↔ 장비 / member_no active | ❌ | ✅ | ✅ |
| AI 뮤직서버 heartbeat·원격 | ❌ | ❌ | ✅ |

---

## 현재 USB 패키지 범위

```
USB zip:     1~4 ✅ (boot-connect · 연동만)
CC 서버:     5~7 orchestrator + phase-bundle API ✅
장비(USB):   register_done 후 GET /install/bootstrap/phase-bundle → pull/ack
다음:        agent runtime · whick-updater
           + boot-connect MVP (LAN reconnect URL UX, § INSTALL-OFFLINE-WIFI-DESIGN §9)
```

**원칙:** USB는 초기 연동(1~4)만. Phase 5~7 스크립트는 CC 서버 bundle — apkovl/zip에 포함하지 않음.


관련 코드:

- Phase 1~2: `boot-connect/whick-boot-connect.sh`, `whick-customer-setup.py`
- Phase 3~4: `boot-connect/templates/install.html`, `cc_client.py` → CC `install.js`
- 부팅: `boot-connect/alpine-local.d-whick-connect.start` → `whick-boot-sequence.sh`
