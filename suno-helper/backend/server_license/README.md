# 서버 라이선스 API 설치 가이드 (whick.org site-api)

## 개요

`backend/server_license/sunoLicense.js`를 whick.org의 CC site-api에 추가하면
Suno Helper 앱의 라이선스 발급/갱신/버전 체널이 동작한다.

## 설치 절차 (서버에서)

### 1. 라이선스 서명 키 생성

```bash
mkdir -p /data/whick-ai/2_control_center/api/keys
openssl genrsa -out /data/whick-ai/2_control_center/api/keys/suno_license_private.pem 2048
openssl rsa -in /data/whick-ai/2_control_center/api/keys/suno_license_private.pem \
  -pubout -out /data/whick-ai/2_control_center/api/keys/suno_license_public.pem
chmod 600 /data/whick-ai/2_control_center/api/keys/suno_license_private.pem
```

### 2. 라우트 파일 복사 + 마운트

```bash
cp sunoLicense.js /data/whick-ai/2_control_center/api/src/packages/site/routes/sunoLicense.js
```

`/data/whick-ai/2_control_center/api/src/packages/site/index.js`의 `mountSitePublic`에 추가:

```js
import sunoLicenseRoutes from './routes/sunoLicense.js';
// mountSitePublic 안에:
app.use('/api/suno', sunoLicenseRoutes);
app.use('/api/v1/suno', sunoLicenseRoutes);
```

### 3. 컨테이너에 키 마운트 + 환경변수

docker-compose (또는 해당 컨테이너 실행 정의)에:

```yaml
    volumes:
      - /data/whick-ai/2_control_center/api/keys:/app/keys:ro
    environment:
      SUNO_LICENSE_PRIVKEY_PATH: /app/keys/suno_license_private.pem
      SUNO_LICENSE_PUBKEY_PATH: /app/keys/suno_license_public.pem
      SUNO_LICENSE_KEY_ID: suno-2026-01
      # 업데이트 체널 (새 버전 배포 시 갱신)
      SUNO_LATEST_VERSION: "1.0.0"
      SUNO_LATEST_NOTES: ""
      SUNO_LATEST_URL: "https://whick.org/downloads/suno-helper"
```

### 4. site-api 컨테이너 재시작

```bash
docker restart whick-cc-site-api
```

### 5. 공개키를 앱에 내장

```bash
cat /data/whick-ai/2_control_center/api/keys/suno_license_public.pem
# → 백엔드 app/services/license_service.py의 LICENSE_PUBLIC_PEM에 붙여넣기
```

## API 요약

| 메서드 | 경로 | 인증 | 용도 |
|---|---|---|---|
| POST | /api/suno/token/new | 로그인(웹) | 활성화 토큰 발급 |
| GET | /api/suno/status | 로그인(웹) | 내 기기 상태 |
| POST | /api/suno/activate | 없음(토큰) | 앱 활성화 → 라이선스 JWT 발급 |
| POST | /api/suno/renew | 없음(라이선스) | 30일 자동 갱신 |
| POST | /api/suno/deactivate | 로그인(웹) | 기기 해지 (이전용) |
| GET | /api/suno/version | 없음 | 업데이트 체널 |

## 응답 형식

site-api 표준 `ok()/fail()` 래퍼 사용 — `{ success: true, data: {...} }` / `{ success: false, code: '...' }`
