# Whick 노트북 테스트 — USB 자동 설치

**Ubuntu 24.04 / 26.04 Desktop** · Wi-Fi 연결 후 사용합니다.

> VIP Room 다운로드: `3_product/docs/LAPTOP-INSTALL-VIP.md`  
> **터널 검증 완료** — SSH 터널 없이 `admin.whick.org` 직접 연결합니다.

---

## USB에 포함된 것

| 파일 | 용도 |
|------|------|
| `whick-3_product/` | runtime 전체 |
| **`Whick-USB-부팅자동.desktop`** | **1회 등록** → 이후 USB 꽂고 부팅·로그인 시 자동 설치 |
| **`Whick-USB-설치.desktop`** | 지금 바로 설치 (더블클릭) |
| `auto-install.sh` | 복사 · Docker · 관제 · runtime (원클릭) |
| `register-login-autostart.sh` | 부팅 자동 등록 |
| `ssh-tunnel-cc.sh` | (선택) SSH 터널 — 보통 불필요 |

---

## 방법 A — 부팅·로그인 자동 (권장)

### 최초 1회 (노트북)

1. USB 연결 → `whick-laptop-usb` 폴더 열기
2. **`Whick-USB-부팅자동.desktop`** 더블클릭 → 「신뢰」/「실행」
3. (선택) 재부팅

### 이후 매번

1. USB 꽂기
2. 노트북 전원 ON → Ubuntu **로그인**
3. **터미널이 자동으로 열리며** 설치 진행 (`sudo` 비밀번호만 입력)
4. 완료 후 **https://admin.whick.org/** → 뮤직서버관제

> 이미 설치된 노트북(`~/.whick-usb-install-done`)은 자동 실행을 건너뜁니다.  
> 재설치: 터미널에서 `WHICK_USB_FORCE=1` 로 `auto-install.sh`

---

## 방법 B — 지금 바로 1회 설치

1. Wi-Fi 연결
2. **`Whick-USB-설치.desktop`** 더블클릭
3. `sudo` 비밀번호 입력 → 완료까지 대기

---

## 방법 C — 터미널 (백업)

```bash
cd /media/$USER/*/whick-laptop-usb
chmod +x *.sh
./auto-install.sh
```

---

## 본사에서 USB 만들기

```bash
cd /data/whick-ai_music_server/3_product
./scripts/build-laptop-usb.sh
# USB에 직접 복사:
./scripts/build-laptop-usb.sh /media/whick/USB이름
```

USB 볼륨 라벨 권장: **`WHICK-LAPTOP`** (파일 관리자에서 구분용)

---

## 확인

```bash
curl -s http://127.0.0.1:8787/health
docker compose -f ~/whick-3_product/compose.yaml ps
```

로그: `~/whick-usb-install.log`

---

## 문제 해결

| 증상 | 조치 |
|------|------|
| desktop이 텍스트로만 열림 | 터미널에서 `./auto-install.sh` |
| `permission denied` docker | 로그아웃 후 재로그인 · `newgrp docker` |
| CC 연결 안 됨 | Wi-Fi 확인 · `curl -s https://admin.whick.org/api/v1/system/health` |
| 자동 실행 안 됨 | `Whick-USB-부팅자동.desktop` 다시 실행 |
| 재설치 | `rm ~/.whick-usb-install-done` 후 `WHICK_USB_FORCE=1 ./auto-install.sh` |

---

## 참고 (본사)

- SSH: `whick@ssh.whick.org`
- CC API: `https://admin.whick.org/api/v1` (노트북 직접)
