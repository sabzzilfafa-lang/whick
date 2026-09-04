# 노트북·미니PC 설치 — VIP Room 다운로드

USB 대신 **whick.org 커뮤니티 VIP Room** 에서 `3_product` 압축 패키지를 받습니다.

## 회원

- **VIP Room** (`annual`) — 솔루션 구입 회원 **Lv3+**
- 로그인 후 **커뮤니티 → VIP Room** → 상단 **공지** 글

## 노트북 (Ubuntu 24.04 / 26.04 · Wi-Fi 연결 후)

### ★ 고객용 (setup.deb — Windows setup.msi 와 같음)

1. VIP Room에서 **파일 2개** — `whick-3product-*.tar.gz` + **`setup.deb`**
2. 같은 **다운로드** 폴더 · `.download` 접미사 있으면 지우기
3. **`setup.deb` 더블클릭** → 「소프트웨어 설치」→ **설치** 버튼
4. 비밀번호 → **터미널이 자동으로 열리며** 설치 (명령어 입력 없음)

> **setup.desktop 은 쓰지 마세요** — Ubuntu가 텍스트로만 엽니다.

**백업:** 다운로드 폴더 빈 곳 → 터미널 →  
`curl -fsSL https://whick.org/whick-content/customer/setup.sh | bash`

자동: 기존 Whick·Docker **전부 삭제** → 압축 해제 → 전원 유지 → Docker → admin.whick.org → agent 기동  
**오류 났을 때**도 같은 방법으로 다시 실행하면 처음부터 재설치됩니다.

> Ubuntu 전용입니다. Windows `.bat` 은 지원하지 않습니다 (runtime이 Linux/Docker).

### 개발·수동 (단계별)

```bash
cd ~/Downloads   # 저장 위치에 맞게
tar xzf whick-3product-*.tar.gz
cd whick-3product
chmod +x scripts/*.sh
./scripts/laptop-first-boot.sh   # ① 전원 유지(sudo) ② Docker
newgrp docker   # 또는 로그아웃·재로그인
```

3. **별 터미널** — CC 터널 유지:

```bash
cd ~/whick-3product
./scripts/ssh-tunnel-cc.sh
```

4. **새 터미널** — runtime:

```bash
cd ~/whick-3product
./scripts/laptop-test-setup.sh
curl -s http://127.0.0.1:8787/health
docker compose logs --tail=20 agent monitor
```

5. 관제: **https://admin.whick.org/** → 뮤직서버관제 · 고객관리

터널 없이: `.env` → `WHICK_CC_API_URL=https://admin.whick.org/api/v1`

전원만 재적용: `./scripts/laptop-power-always-on.sh apply`

## USB 자동 설치 (오프라인·저녁 테스트)

본사에서 USB 번들 생성 후 노트북에 꽂기:

```bash
cd /data/whick-ai_music_server/3_product
./scripts/build-laptop-usb.sh /media/USER/USB이름
```

노트북: `whick-laptop-usb` → **`Whick-USB-부팅자동.desktop`** (1회) → 부팅·로그인 시 자동 설치.  
상세: `usb-bundle/START-HERE.md`

## 운영자 — 패키지 갱신·게시 (본사 서버)

```bash
cd /data/whick-ai_music_server/3_product
./scripts/publish-to-vip-room.sh
```

압축 + desktop 생성:

```bash
./scripts/build-3product-zip.sh   # dist/whick-3product-*.tar.gz + setup.desktop + setup.sh
```
