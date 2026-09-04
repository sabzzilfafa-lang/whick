# 원격 단계 5~7 — 서버(CC) API 준비

**갱신:** 2026-06-18  
**상위:** [INITIAL-INTEGRATION-PHASE.md](INITIAL-INTEGRATION-PHASE.md) (1~4 완료)

---

## 단계별 서버 준비 상태

| # | 단계 | CC API | 상태 |
|---|------|--------|------|
| **5** | Linux/SSD 설치 진행 | `PATCH /install/sessions/:id/progress` | ✅ |
| | 동의 (설치 전) | `POST /install/consent` | ✅ |
| | community HW 진행 | `POST /install/proceed-anyway` | ✅ |
| **6** | agent 등록·heartbeat | `POST /agent/register`, `/agent/heartbeat` | ✅ (기존) |
| | runtime 정책 | `GET /agent/policy` | ✅ (기존) |
| **7** | 원격 조작 | `musicServers` → `cc_agent_commands` | ✅ (기존) |
| | OTA 업데이트 배달 | `GET /agent/updates/pending`, `POST /agent/updates/:id/report` | ✅ |
| | apply_update 명령 | `COMMAND_DEFS.apply_update` | ✅ |

**B-path (출고):**

| API | 설명 |
|-----|------|
| `POST /install/factory-bind` | Whick 입고 설치 · order_id · unclaimed |
| `POST /install/claim-device` | 고객 수령 후 claim + member_no |
| `GET /install/devices/:serial/claim-status` | first-boot claim 폴링 |

---

## DB

```bash
docker exec -i -e PGPASSWORD=whick_cc_dev_pass whick-cc-db \
  psql -U cc_app -d whick_control -f /data/whick-ai/2_control_center/db/pg-init/03-cc-ops.sql
```

| 테이블/컬럼 | 용도 |
|-------------|------|
| `cc_ops.cc_install_consents` | wipe/terms/community 동의 감사 |
| `cc_core.cc_devices.claim_status` | claimed / unclaimed / preinstalled |

---

## install phase (progress PATCH)

`installProgress.js` SSOT:

- `install_linux` → `install_docker` → `install_runtime` → `complete`
- `failed` — 오류 시

bootstrap Bearer `bst_…` + session id 일치 필요.

### Phase script bundle (USB 연동 후)

| API | 설명 |
|-----|------|
| `GET /install/bootstrap/phase-bundle` | phases 5~7 tar.gz (bootstrap Bearer, `register_done`+) |
| `GET /install/bootstrap/phase-bundle/meta` | bundle version + file sha256 |

USB apkovl에는 **포함하지 않음** — CC 서버 `uab/live/` SSOT.

---

## Agent OTA (Phase 7)

1. 관제 `updates.js` — `cc_device_updates.status = queued`
2. agent `GET /updates/pending` — 대기 목록 + 자동 `apply_update` command enqueue
3. agent 실행 후 `POST /updates/:id/report` — completed / ai_failed

장비 측 `whick-updater` 패키지는 별도 (3_product/updater).

---

## 코드 위치

| 파일 | 역할 |
|------|------|
| `2_control_center/api/src/routes/install.js` | install API 전체 |
| `2_control_center/api/src/lib/installProgress.js` | phase 5~7 progress |
| `2_control_center/api/src/lib/installConsent.js` | consent / proceed |
| `2_control_center/api/src/lib/installFactory.js` | factory / claim |
| `2_control_center/api/src/lib/updateAgentDelivery.js` | OTA → agent command |
| `2_control_center/api/src/routes/agent.js` | updates/pending, updates/report |

---

## 아직 장비(UAB) 쪽

- `uab/live/phases/*.sh` — real install scripts
- `bootstrap-agent.py` — PATCH progress during phases
- `3_product/updater/` — poll + apply_update handler
- `3_product/agent` — `apply_update` command handler

서버 API는 위 항목을 연결할 준비가 되어 있습니다.
