# packages/remote — Whick 판매용 리모컨 PWA (v4)

이 디렉터리가 판매용 리모컨 UI의 **독립 SSOT**다. 제품 변경은 여기에서
직접 개발·검토하며, 체험 site-web 소스를 복사·동기화·import·symlink·hardlink
하지 않는다.

| 파일 | 설명 |
|------|------|
| `index.html` | 판매 포털에서 여는 v4 UI |
| `js/remote_api.js` | 고객 뮤직서버 WebSocket + REST 클라이언트 |
| `js/whick-spatial-wizard.js` | 공간음향 서버 MPD 스윕 |

## 제품 경로와 API

- 포털: `https://remote.whick.org/` — 로그인·설치·기기 선택
- UI: `/v4/index.html?embed=1&device=…`
- 고객 뮤직서버: LAN `http://{host}:8080` 또는 고객별 Cloudflare Tunnel
- 실시간 제어: `/ws`
- 제품 REST: `/api/state`, `/api/tracks`, `/api/playback/*`, `/api/dsp/*`,
  `/api/library/*`, `/api/streaming/*`
- 장비 프로필: CC `/remote/devices`

체험은 별도 site-web 경로와 `/api/site/trial/*` API를 사용한다. 이 경로/API를
판매용 번들에서 호출하거나 fallback으로 두지 않는다.

## 배포 전 검증

```bash
3_product/scripts/guard-product-remote-separation.sh
```

과거 `sync-trial-remote-to-product.sh`는 안전을 위해 항상 실패하며 사용할 수
없다. 검증 통과 후에만
`packages/remote-portal/scripts/deploy-remote-portal.sh`로 재빌드한다.

설계: [../../docs/REMOTE-DESIGN.md](../../docs/REMOTE-DESIGN.md)
