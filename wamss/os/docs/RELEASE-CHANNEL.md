# Whick OS — 릴리스 채널 (CC 솔루션 whick-os 삭제 · 2026-07-26)

| 채널 | 아티팩트 | CC 등록 |
|------|----------|---------|
| Live 유선 ISO | `whick-os-live-wired.iso` | **`connect-wired`** |
| Live 무선 ISO | `whick-os-live-wireless.iso` | **`connect-wireless`** |
| SSD rootfs | `whick-os-rootfs.tar.xz` | **`music-01`** components 핀 |
| Rescue | `whick-os-rescue.tar.zst` | 빌드 산출 (설치 경로) |

## 등록

```bash
WHICK_USB_PROFILE=wired    bash 3_product/uab/scripts/release-connect-usb.sh --no-bump --skip-publish
WHICK_USB_PROFILE=wireless bash 3_product/uab/scripts/release-connect-usb.sh --no-bump --skip-publish
# 또는 ISO만:
bash /data/whick-ai/2_control_center/scripts/register-solution-cc.sh connect-wired
bash /data/whick-ai/2_control_center/scripts/register-solution-cc.sh connect-wireless
```

## 공지

- 홈 버전공지(#2239)는 **알파/music 핀** 중심
- Live ISO 변경은 connect-wired / connect-wireless 릴리스 노트

## 알파

서비스 패키지 4종: music-01 · remote-mobile · connect-wired · connect-wireless  
(CC `whick-os` 솔루션 없음 — 빌드 스크립트명만 `whick-os-*` 유지)
