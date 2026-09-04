# Whick USB 부팅 — 고객 흐름

## 단계 구분

| 구분 | 번호 | 내용 |
|------|------|------|
| **초기 연동** | **1~4** | 세션 → hw_id → 고객 바인딩 → 회원번호 active (**여기까지 준비 필수**) |
| **원격 단계** | **5~** | SSD/runtime 설치 → agent → 관제 리모트 |

상세: [`docs/INITIAL-INTEGRATION-PHASE.md`](docs/INITIAL-INTEGRATION-PHASE.md)  
**오프라인 Wi-Fi (AP → :8765 → CC 1~4):** [`docs/INSTALL-OFFLINE-WIFI-DESIGN.md`](../../docs/INSTALL-OFFLINE-WIFI-DESIGN.md)  
원격 5~7 서버 API: [`docs/REMOTE-PHASE-SERVER.md`](docs/REMOTE-PHASE-SERVER.md)

---

## 초기 연동 1~4 (요약)

| # | 단계 | API | USB 패키지 |
|---|------|-----|------------|
| 1 | 설치 세션 `MUSIC-xxxx` | `POST /install/sessions` | ✅ |
| 2 | hw_id 등록 | `POST /install/hw-report` | ✅ |
| 3 | whick.org 로그인 → 고객 바인딩 | 폰 `POST /api/register` → 미니PC → CC `register-product` | ✅ |
| 4 | 회원번호 active (`msnt-…`) | register-product 내부 | ✅ |

**현재 USB zip:** 초기 연동 **1~4** (세션 → hw_id → whick.org 로그인 → 회원번호).  
스마트폰 UI: **LAN IP** 또는 **whick.org 고유 접속 주소** (가상 AP·whick.setup 폐기).

---

## 고객 전체 흐름 (구매 ~ 원격)

| 단계 | 장소 | 내용 |
|------|------|------|
| 0 | whick.org | 솔루션 구매 → `member_no` 설치대기 (CC) |
| 1~2 | 미니PC USB | 서버 연결 · hw_id |
| 3~4 | 미니PC USB | whick.org 로그인 · 장비 등록 · 회원번호 확정 |
| 5~7 | 원격 | OS/솔루션 설치 · agent · 관제 리모트 |

---

## Windows USB Maker (고객 UI)

1. USB를 꽂아 주세요  
2. USB 선택  
3. 동의 → USB 만들기  
4. 미니PC USB 부팅 → 유선 연결 또는 (무선 VIP) 사전 입력 Wi-Fi 자동 연결 → 고유 접속 주소

---

## 본사 — 릴리스 (제품별 · 버전 SSOT)

**카탈로그:** `/data/whick-ai/2_control_center/config/solutions-catalog.json`  
**버전 파일:** `config/solutions/<code>.json` · **현황:** `solutions-version-status.sh`

| 제품 | code | 버전 라인 | 릴리스 |
|------|------|-----------|--------|
| USB 무선 | `connect-wireless` | v0.1.x | `WHICK_USB_PROFILE=wireless ./release-connect-usb.sh` |
| USB 유선 | `connect-wired` | v0.1.x | `WHICK_USB_PROFILE=wired ./release-connect-usb.sh` |
| 미니PC 뮤직플레이어 | `music-01` | v1.0.x | `3_product/scripts/release-music-server.sh` |
| 모바일 리모컨 | `remote-mobile` | v0.1.x | `packages/remote-portal/scripts/release-remote-mobile.sh` |

```bash
# USB (유선 기본)
cd /data/whick-ai_music_server/3_product/uab/scripts
./release-connect-usb.sh
WHICK_USB_PROFILE=wireless ./release-connect-usb.sh

# 전체 현황
/data/whick-ai/2_control_center/scripts/solutions-version-status.sh
```

**Cursor 규칙:** 패키지 수정 완료 → 해당 제품 release 스크립트 1회 (패치 bump · CC · VIP/PWA 자동).

## 본사 — 연결 스크립트 검증

```bash
./boot-connect/whick-boot-connect.sh
cat /tmp/whick-connect-result.json
```

---

## DB

`cc_core_app` → `cc_ops.cc_install_sessions` / `cc_install_hw_reports`  
→ `2_control_center/db/62-install-sessions-core-grant.sql`

---

## 테스트

```bash
./scripts/test-connect-suite.sh
```
