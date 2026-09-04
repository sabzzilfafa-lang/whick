# 3_product 작업 격리 원칙 (필수)

**갱신:** 2026-06-08  
**Phase 0:** [PHASE-0-BASELINE.md](PHASE-0-BASELINE.md) — **3종 저장·동결** · 구현만 `3_product/agent|audio|packages|…`  
**한 줄:** 완성된 **홈·통합관제·설계 SSOT는 수정하지 않는다.** 제품 **코드**는 **`3_product/` 복사본**만 편집.

---

## 1. 건드리지 않을 것 — **3종 저장** 🔒

상세: [PHASE-0-BASELINE.md](PHASE-0-BASELINE.md)

| 종 | 경로 |
|----|------|
| **1 홈·체험** | `5_site/` · `music-server/` |
| **2 통합관제** | `/data/whick-ai/2_control_center/` |
| **3 제품 설계** | `install/` · `3_product/docs/` · `3_product/README.md` · `compose.yaml` · `.env.example` |

---

## 2. 제품 독립 영역에서만 작업 — **Phase 1 구현 구역**

`3_product/`는 판매 제품만 소유한다. 홈·체험·demo·CC에서 파일을
복사하거나 동기화하지 않고 제품 요구사항을 이 영역에서 독립 구현한다.

| 허용 | 금지 |
|------|------|
| 요구사항·프로토콜 문서 참고 후 제품에 독립 구현 | 홈·체험·demo 코드를 복사·동기화 |
| **`3_product/agent/`** · **`audio/`** · **`packages/`** · **`remote/`** | `install/` · `3_product/docs/` · 설계 doc 수정 |
| CC API **호출** (agent outbound) | 관제 **코드** 수정 |

**심볼릭 링크**로 `5_site`/`music-server`를 묶지 **않음** — 배포 단위 완전 분리.

---

## 3. `music-server/` 위치

- `music-server/`는 레거시 참고 트리이며 현재 홈·제품·CC로 publish하지 않는다.
- 제품 개발은 **`3_product/packages/`** 에서만 독립 구현한다.
- 프로토콜 변경이 필요해도 다른 UI 파일을 함께 수정하지 않는다.

---

## 4. 통합관제 연동

- agent → CC **기존 API** (`/agent/register`, heartbeat) **사용** (관제 코드 수정 없이).
- API **부족** 시: `3_product/docs/API-NEEDS.md`에 요구사항만 적고, 관제 변경은 **별도 PR/세션**.

---

## 5. Cursor / AI 작업 시

1. 작업 경로 **`3_product/**` 로 한정  
2. `5_site` · `2_control_center` diff **없어야 함**  
3. 다른 UI에서 파일을 복사하지 말고 경계 guard를 실행  

규칙 파일: [`.cursor/rules/03-product-isolation.mdc`](../../.cursor/rules/03-product-isolation.mdc)

---

## 6. 검증

```bash
# 제품 작업 후 — 홈/관제 미변경 확인 (예)
git status -- 5_site/ /data/whick-ai/2_control_center/
# → 변경 없음이 정상
```
