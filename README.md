# 3_product — 고객 미니PC 뮤직서버 (제품 OS)

**SSOT:** 이 폴더 = 고객 SSD에 올라가는 **Whick 솔루션 전체** (Ubuntu 26.04 위 Docker runtime).

> **Phase 0 (2026-06-08):** [docs/PHASE-0-BASELINE.md](docs/PHASE-0-BASELINE.md) — **3종 저장·동결** · **agent/audio/packages 만 개발**

| | `5_site` 체험 | `3_product` 제품 |
|--|---------------|------------------|
| 실행 위치 | whick.org · PC 브라우저 | **고객 미니PC** (24/7) |
| UI | trial-player · 그누보드 | **없음** (스마트폰 리모컨만) |
| 재생 | 브라우저 Web Audio | **agent → CamillaDSP → DAC** |

## 노트북·미니PC 설치

- **VIP Room 다운로드 (권장):** [docs/LAPTOP-INSTALL-VIP.md](docs/LAPTOP-INSTALL-VIP.md)
- **USB 자동 설치:** `scripts/build-laptop-usb.sh` → `Whick-USB-부팅자동.desktop` (로그인 autostart)

## 문서

- [docs/ISOLATION.md](docs/ISOLATION.md) — **홈·관제 미수정 · 복사본만 편집 (필수)**
- [docs/SCOPE.md](docs/SCOPE.md) — 포함·제외 범위
- [docs/REMOTE-DESIGN.md](docs/REMOTE-DESIGN.md) — **리모컨 v4 · WS/REST 계약**
- [docs/TRIAL-TO-PRODUCT.md](docs/TRIAL-TO-PRODUCT.md) — 체험 → 제품 이식 매핑
- [../install/UAB-USB-SOFTWARE.md](../install/UAB-USB-SOFTWARE.md) — USB는 **본 폴더 완성 후** 실증
- [../docs/MUSIC-SERVER-AGENT.md](../docs/MUSIC-SERVER-AGENT.md) — agent 아키텍처

## 폴더

```
3_product/
├── compose.yaml          # 고객 runtime (SSD)
├── .env.example
├── agent/                # whick-agent · CC · remote_cmd
├── audio/                # CamillaDSP · ALSA
├── library/              # 로컬 음원 (TBD)
├── local-ai/             # Ollama gemma4:e2b sidecar (관제 보조, TBD)
├── monitor/              # 관제담당 L1 → CC protocol v1
├── updater/              # CC OTA
├── remote/               # 스마트폰 API · claim (B경로)
│   └── api/              # music_api.py (FastAPI · v4 계약)
└── packages/             # 제품 전용 독립 패키지
    └── remote/           # index.html + js/remote_api.js (v4)
```

## `music-server/` 와 관계

- **`music-server/`** — 레거시 참고 코드 · 제품과 동기화 금지
- **`3_product/packages/`** — 제품 전용 독립 SSOT (다른 UI에서 복사 금지)
- **`3_product/`** — **배포 단위** (Docker · env · systemd)

## 구현 순서 (확정)

1. **SCOPE** 확정 → **agent + audio** PoC  
2. **스마트폰 ↔ agent** (체험 `remote_cmd` 계승)  
3. **compose** 로 dev 미니PC 1대 기동  
4. 이후 **UAB USB** (`install/bootstrap/`) 가 본 폴더를 SSD에 배포

## 로컬 dev (추가 예정)

```bash
cd 3_product && docker compose --env-file .env.example config
```
