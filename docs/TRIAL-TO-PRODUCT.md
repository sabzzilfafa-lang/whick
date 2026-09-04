# 체험과 제품 분리 원칙

이 문서는 체험 코드를 제품으로 이식하는 절차가 아니다. 체험과 제품은 목적,
라우팅, 인증, 실행 환경이 다른 독립 시스템이다.

## SSOT 경계

- 판매용 리모컨 UI SSOT: `3_product/packages/remote/`
- 체험 UI SSOT: control-center의 site-web 체험 소스
- 제품 코드는 체험 소스를 복사·동기화·import·symlink·hardlink하지 않는다.
- 공통 기능이 필요하면 제품 요구사항과 제품 API 계약에 맞춰 제품 SSOT에서
  독립적으로 구현한다.
- 과거 동기화 스크립트는 폐기되었으며 실행하면 항상 실패한다.

## 경로와 API 경계

| 구분 | 브라우저 경로 | 데이터 경로 |
|------|---------------|-------------|
| 제품 | `remote.whick.org/v4/` | 고객 뮤직서버 `/ws`, `/api/state`, `/api/tracks`, `/api/playback/*`, `/api/dsp/*`, `/api/library/*`, `/api/streaming/*` |
| 체험 | whick.org의 `/trial-remote/` | control-center `/api/site/trial/*` |

제품 번들에는 체험 URL, 체험 API fallback, 체험 전용 호스트·플래그를 두지
않는다. 제품 연결은 포털의 장비 프로필과 고객별 LAN/Cloudflare Tunnel
endpoint만 사용한다.

## 개발과 검증

1. 제품 변경은 `packages/remote/`에서 직접 구현한다.
2. 제품 API 계약은 [REMOTE-DESIGN.md](REMOTE-DESIGN.md)를 따른다.
3. 배포 전에 아래 guard를 실행한다.

```bash
3_product/scripts/guard-product-remote-separation.sh
```

guard는 제품 런타임 파일의 명확한 체험 경로·API·호스트·플래그와, 체험
소스에 연결된 symlink/hardlink를 거부한다. 체험 소스가 로컬에 없으면
내용 검사는 계속하고 inode/link 비교만 건너뛴다.

홈·관제 체험 소스는 제품 작업에서 수정하거나 배포하지 않는다
([ISOLATION.md](ISOLATION.md)).
