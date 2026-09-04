# CC API — device protocol v1

**SSOT:** [DEVICE-CC-PROTOCOL.md](DEVICE-CC-PROTOCOL.md)  
**CC 구현:** `/data/whick-ai/2_control_center/api/src/routes/`  
**DB:** `2_control_center/db/09-install-monitor-library.sql`

| API | 상태 | CC 경로 |
|-----|------|---------|
| POST `/install/sessions` | ✅ 초안 | `install.js` |
| GET `/install/sessions/:id` | ✅ 초안 | |
| POST `/install/hw-report` | ✅ 초안 | bootstrap auth |
| GET `/install/sessions/:id/hw-result` | ✅ 초안 | |
| POST `/install/register-product` | ✅ 초안 | bootstrap auth |
| POST `/agent/register` | ✅ 기존 | `agent.js` |
| POST `/agent/heartbeat` | ✅ 기존 | |
| POST `/agent/monitor-snapshot` | ✅ 초안 | whick-monitor |
| POST `/agent/library-jobs` | ✅ 초안 | |
| GET `/agent/library-jobs/:job_id` | ✅ 초안 | |
| POST `/agent/attest` | ✅ 초안 | |
| GET `/agent/policy` | ✅ 초안 | |
| GET `/music-servers/library-jobs/queue` | ✅ 초안 | JWT staff |
| POST `/music-servers/library-jobs/:id/claim` | ✅ 초안 | |
| POST `/music-servers/library-jobs/:id/result` | ✅ 초안 | |
| POST `/install/consent` | ⏳ | |
| POST `/install/factory-bind` | ⏳ | |
| POST `/install/claim-device` | ⏳ | |

**마이그레이션 적용:**

```bash
mysql whick_control < /data/whick-ai/2_control_center/db/09-install-monitor-library.sql
```

**로컬 검증 (install 흐름):**

```bash
# 1) session
curl -s -X POST http://127.0.0.1:8090/api/v1/install/sessions \
  -H 'Content-Type: application/json' \
  -d '{"install_path":"diy"}'

# 2) hw-report (bootstrap_token from step 1)
# 3) register-product
```
