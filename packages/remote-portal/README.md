# packages/remote-portal — Whick Remote 독립 포털

**도메인:** `https://remote.whick.org`  
**역할:** whick.org 홈 **없이** Whick 계정 로그인 → 내 뮤직서버 선택 → (향후) v4 리모컨 PWA

| 파일 | 설명 |
|------|------|
| `index.html` | 로그인 · 장비 목록 · 리모컨 진입(placeholder) |
| `js/portal_auth.js` | CC `/api/v1/remote/*` 클라이언트 |
| `icons/source-remote.png` | 아이콘 원본 (홈·CC 스타일 steampunk 리모컨) |
| `icons/export-from-source.py` | PWA PNG·favicon 생성 |
| `manifest.webmanifest` | Chrome·Android 홈화면 설치 |
| `sw.js` | PWA install criteria (network-first) |
| `nginx.conf` | 정적 + CC API reverse proxy |

아이콘 재생성:

```bash
python3 icons/export-from-source.py
./scripts/deploy-remote-portal.sh
```

설계: [../../docs/REMOTE-PORTAL.md](../../docs/REMOTE-PORTAL.md)  
리모컨 UI SSOT: [../remote/index.html](../remote/index.html)  
플레이리스트 공유(예정): [../../docs/PLAYLIST-SHARE.md](../../docs/PLAYLIST-SHARE.md)

## 로컬 기동

```bash
./scripts/deploy-remote-portal.sh
# → http://127.0.0.1:8097
```

## 운영 반영

1. CC API에 `remotePortal` 라우트 배포 (`whick-cc-api-core` restart)
2. `./scripts/deploy-remote-portal.sh`
3. Cloudflare DNS `remote.whick.org` CNAME → 터널
4. `sudo /data/whick-ai/0_gateway/scripts/sync-tunnel-config.sh`
