# Whick SSD partition layout (Phase 5)

**root(install) 예약은 이원화 고정값 — 128GB 미만(64GB eMMC 포함) 32GB / 128GB 이상 64GB.**
향후 시스템 업데이트로 root가 부족해도 파티션을 다시 나눌 수 없어, 처음부터 여유 있게 2단계로 고정한다.
**나머지 전부 음원저장소.**

| 영역 | 용량 | 마운트 | 비고 |
|------|------|--------|------|
| EFI | 512 MiB | `/boot/efi` | UEFI만 |
| Install | **32 GB**(<128G) / **64 GB**(>=128G) | `/` | OS · Docker · runtime · Ollama |
| Music | **나머지 전부** | `/mnt/music` | 라벨 `whick-music` (2번째 이상 SSD는 `/mnt/music/diskN`) |

~~Rescue 파티션~~ — **설계 폐기 (2026-07-26)**. 원격 `system_reinstall` 없음.  
전체 재설치(OS) = **VIP USB Live** · 관제 = `runtime_reinstall`(Docker) 까지.

시뮬레이션:

| SSD 용량(제조사 표기, decimal GB) | System | Music |
|----------|--------|-------|
| 64 GB (eMMC) | **32 GB** | ~23 GB |
| 120 GB | **32 GB** | ~75 GB |
| 128 GB | **64 GB** | ~51 GB |
| 250 GB | **64 GB** | ~164 GB |
| 500 GB | **64 GB** | ~397 GB |
| 1 TB | **64 GB** (고정) | ~863 GB |

제조사 표기 용량(decimal GB, 10^9)과 lsblk 크기(GiB, 1024^3)는 다르다 — "128GB" 실제
디스크는 lsblk 기준 ~119GiB로 보인다. `WHICK_ROOT_TIER_THRESHOLD_GB` 기준값을 112로 낮춰
128GB급이 32GB tier로 잘못 분류되지 않게 여유를 뒀다.

환경 변수 (`live/lib/whick-disk.env`):

- `WHICK_ROOT_TIER_THRESHOLD_GB=112` — 이원화 기준선 (GiB 기준, 128GB decimal 여유 포함)
- `WHICK_ROOT_SMALL_GB=32` — threshold 미만 root
- `WHICK_ROOT_LARGE_GB=64` — threshold 이상 root
- `WHICK_INSTALL_RESERVE_GB` — 값을 지정하면(랩 테스트 등) 이원화를 무시하고 그 값을 강제. **운영 환경에서는 비워둘 것.**
- `WHICK_INSTALL_MIN_GB=32` — 초소형(랩 루프백 등) 디스크의 최소 root
- `WHICK_MUSIC_MIN_GB=15` — 최소 music
- `WHICK_RESCUE_ENABLE=0` — **항상 0 (폐기)**. 켜지 말 것.

## 업데이트 시 디스크 정리

`apply_update`(OTA) · `rebuild` · `dev_pull` 완료 후 에이전트가 `docker image prune -af`
(로컬 빌드 경로는 `docker builder prune -f`도)를 실행해 교체된 이전 이미지·빌드 캐시를
자동 삭제한다 (`3_product/agent/src/docker-ops.mjs`, `dev-ops.mjs`). root가 32~64GB로
고정이라도 매 업데이트마다 이전 버전 잔여물이 쌓이지 않아 디스크 여유가 유지된다.

다만 업데이트 실패로 새 버전이 정상 기동하지 못하는 경우를 대비해 **직전 1개 버전의
이미지는 무조건 보존**한다. 업데이트 시작 시 현재 도는 이미지 ID를 기록해두고, 새 버전
기동 성공 후 그 이미지들을 `whick-keepimg-N`이라는 정지 상태 컨테이너로 anchor(참조)
시켜 `prune -a`가 지우지 못하게 한다. 다음 업데이트 때는 2버전 전 anchor를 먼저 지우고
이번 직전 버전을 새로 anchor하므로, 항상 "현재 + 직전 1개"만 남고 그 이전은 정리된다.

## 재설치 규칙

1. **기존 `/mnt/music` 파티션** (`whick-music` 라벨 또는 mount) → **절대 wipe 금지**
2. OS 파티션만 재생성 (USB Live 재설치)
3. 신규 디스크 → EFI + root + music 분할
4. **전체 재설치** = USB Live · **Docker만** = 관제 `runtime_reinstall`

## 도구

```bash
# 계획만 (destructive 아님)
python3 live/bin/disk_plan.py --plan

# 실제 파티션 적용 (Ubuntu UAB / curtin)
WHICK_LINUX_INSTALL_DRY_RUN=0 WHICK_DISK_APPLY=1 ...
```

USB boot-connect: `register_done` 후 CC orchestrator 명령 pull — phase 스크립트는 `GET /install/bootstrap/phase-bundle` (서버 SSOT).
