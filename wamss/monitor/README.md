# whick-monitor — 고객 미니PC 관제담당 (L1)

**역할:** 장비 metrics · runtime 서비스 상태 · library incoming 감지 → CC 전송 · library job 생성.

- SSOT 통신: [docs/DEVICE-CC-PROTOCOL.md](../docs/DEVICE-CC-PROTOCOL.md)
- 본사 `1_brain/staff/monitor` **포크 아님** — 제품 전용 슬림 구현
- `agent`가 `/agent/register` 후 발급한 **`WHICK_AGENT_TOKEN` 공유**

## 환경변수

| 변수 | 설명 |
|------|------|
| `WHICK_CC_API_URL` | CC base (`…/api/v1`) |
| `WHICK_AGENT_TOKEN` | `agt_…` |
| `WHICK_DEVICE_SERIAL` | `hw_id_hash` (= register 시 serial) |
| `WHICK_MONITOR_INTERVAL_SEC` | snapshot 주기 (기본 30) |
| `WHICK_LIBRARY_INCOMING` | incoming 폴더 (기본 `/var/lib/whick/library/incoming`) |

## 로컬 실행 (PoC)

```bash
cd 3_product/monitor
npm install
WHICK_CC_API_URL=http://127.0.0.1:8090/api/v1 \
WHICK_AGENT_TOKEN=agt_… \
WHICK_DEVICE_SERIAL=… \
node src/main.mjs
```

## Docker

`compose.yaml` 의 `monitor` 서비스 — agent 기동 후 token이 `.env`에 있어야 함.
