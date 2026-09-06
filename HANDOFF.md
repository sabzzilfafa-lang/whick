# Handoff — Suno Helper 배포 계획 (로컬 실행 + 웹 인증서 모델)

> 최종 아키텍처 (확정): **완전 SaaS 아님.** 모든 실행·저장은 사용자 PC.
> whick.org는 로그인 → 설치파일 배포 → 인증서 발급 → 업데이트 배포만 담당 (WAMSS와 동일 패턴).

## 확정된 아키텍처

```
[whick.org 서버 (/data/suno-helper)]      [사용자 PC]
  · 로그인 (기존 whick 계정)                · 설치: install.bat (Node 불필요)
  · 설치파일 다운로드 (버전별 zip)           · 로컬 앱: FastAPI(8765) + 프론트 빌드본
  · 인증서 발급/갱신 API                    · 실행·저장 전부 로컬 (ffmpeg/Whisper/DB/파일)
  · 버전 메타데이터 (업데이트 채널)           · API 키: OpenRouter·YouTube 각자 것
  · 내 기기 관리, 매뉴얼/FAQ
```

홈페이지가 관리하는 것: **계정, 설치 배포, 인증서, 업데이트, 설정 템플릿 배포(선택)**
로컬이 처리하는 것: **운영 전부** (프라이버시 — "No tracking" 원칙 유지, 원격 설정 강제 없음)

---

## Phase A — 인증서(라이선스) 체계

### 웹 API 계약 (whick.org, /data/suno-helper에 배포)

| 엔드포인트 | 역할 |
|---|---|
| `POST /api/suno/activate` | `{install_token, machine_id}` → 서명된 라이선스 JWT 발급 |
| `POST /api/suno/renew` | 기존 인증서로 연장 발급 (자동 갱신용) |
| `GET /api/suno/version` | `{version, notes, url, sha256}` 업데이트 메타데이터 |
| `GET /api/suno/download/{ver}` | 설치 zip (로그인 게이트) |
| 기기 관리 페이지 | 내 설치 목록/해지 (계정당 설치 수 제한 정책 필요) |

- 서명: **RS256 JWT** — 서버 개인키로 서명, 앱에는 공개키만 내장. 서버 DB 유출돼도 위조 불가
- 페이로드: `{product:"suno-helper", user_id, machine_id, plan, iat, exp}`
- machine_id: 하드웨어 GUID 해시 (개인정보 아님, 재설치 시 동일)

### 로컬 앱 변경 (신설 `license_service.py`)

- 시작 시 `data/license.json` 검증: 서명·기기 일치·만료 → 상태 API + UI 표시
- 갱신: 만료 임박(7일 전) 백그라운드 자동 갱신 (온라인 1회, 사용정보 전송 없음 — machine_id+인증서만)
- 만료 동작: **유예 30일 경고 → 이후 신규 작업 잠금, 기존 결과물은 열람 가능** (강도는 조정 가능)

## Phase B — 설치기 (Installer)

- 패키지: `SunoHelper-Setup-{ver}.zip` = 백엔드 소스 + **프론트 빌드본(dist)** + `install.bat` + 매뉴얼
- `install.bat`: Python 존재 확인(없으면 공식 다운로드 안내) → venv 생성 → 고정된 requirements 설치 → 바로가기 생성 → 첫실행 마법사 오픈
- **고객 PC 요구사항: Python만** (프론트 빌드포함 → Node 불필요)
- ffmpeg: 설치 시 공식 빌드 다운로드(체크섬 검증) 또는 zip 포함 — 라이선스 검토 후 결정
- 제외: `data/`, `logs`, `.git`, 개발 스크립트(`_probe.py` 등), `HANDOFF.md`
- 언인스톨러 + 데이터 보존 안내

### 첫실행 마법사 (신규 UX, 배포 핵심)

1. 라이선스 인증 (홈페이지 토큰 붙여넣기 or 브라우저 연동)
2. 작업 폴더 지정 (기본 `D:\YouTubeMusic` 안내)
3. **채널 브랜드 설정** (채널명·©문구 — 비워두면 자동 생략)
4. API 키 안내 (OpenRouter / YouTube OAuth 가이드 링크)
5. 환경 점검: ffmpeg·폰트·Whisper 모델(첫 자막 생성 시 다운로드 안내)

## Phase C — 업데이트 채널

- 앱 시작 시 `GET /api/suno/version` 확인 (기기 고유정보 미전송) → 새 버전이면 배너+다운로드 링크
- 업데이트 = 새 설치 zip 실행. `data/`, `.env`는 절대 건드리지 않음 (설치기가 보존)
- 버전 관리: `app.version` 현재 `0.1.0` → 정식 버전 체계 시작 (예: `1.0.0`)
- 선택: 설정 템플릿(프리셋·브랜드 기본값)도 버전 채널로 배포 가능

## Phase D — 앱 정리 (배포 품질) — ✅ 2026-09-07 완료 (i18n 제외)

1. ✅ **브랜드 기본값 초기화** — `DEFAULT_BRAND` 전부 빈 값. 폴백 제거:
   - `playlist_pipeline_service.py` "© WHICK Official" 폴백 제거
   - `thumbnail_canvas_service.py` "© My Channel" 폴백 제거
   - `watermark_service.py` 기본 아이콘/라벨 폴백 제거 (사용자 아이콘+채널명 없으면 워터마크 자체 생략)
   - `editor_service.py`·`desc_blocks_service.py` 기본 해시태그 폴백 제거
   - `EditorPage.tsx` 미리보기 워터마크: 브랜드 미설정 시 숨김, 라벨은 brand 설정값 사용
   - 검증: brand.json 없는 신규 설치 시나리오에서 생성물에 브랜드 문구 0건 확인
2. ⏳ **i18n** — 다음 단계에서 별도 진행 (react-i18next, ko/en)
3. ✅ **폰트 폴백** — `font_resolver.py` 신설 + Noto Sans KR 3종 번들(`backend/app/assets/fonts/`, OFL)
   Windows 맑은고딕 우선 → 번들 폴백. watermark/썸네일/ASS 자막 모두 리졸버 경유.
   `pipeline_defaults.font_name` 빈 값 = 환경 자동 선택
4. ✅ **requirements.txt 고정** — pip freeze 기준 핀 버전
5. ✅ **Intel QSV/MF 인코딩 인자 분기 추가** — `h264_qsv`(global_quality ICQ), `h264_mf`(quality rc).
   감지는 기존 `_encoder_actually_works` 실측 방식 유지
6. ✅ **버전 1.0.0 + 업데이트 채널 기본 구조** — `update_service.py` (APP_VERSION SSOT,
   `GET /api/version` — 신규, `/api/health`에 version 포함). whick.org 버전 API URL은 env `SUNO_UPDATE_URL`

## Phase E — 문서·상용화

- 고객용: 설치 매뉴얼, Google OAuth 발급 가이드, 첫 실행 안내(모델 다운로드 시간), FAQ
- 결제: 인증서 발급을 결제와 연동 (국내 PG) — 무료 체험 인증서(기간제) → 유료 전환 구조 가능
- 이용약관·개인정보 처리방침, Suno 상업이용 고지

---

## 진행 순서 (권장)

1. **Phase D** (앱 정리 — 기존 코드 작업, 즉시 가능) + **Phase C 버전 체계**
2. **Phase A** 인증서 (로컬 검증 모듈 + /data/suno-helper 참조 API 구현)
3. **Phase B** 설치기 + 첫실행 마법사
4. **Phase D-i18n** (범위 큼 — ko/en부터 페이지별)
5. **Phase E** 문서·결제

## 폐기된 이전 계획 (완전 SaaS)

다중 사용자 테넌시 / Postgres / Redis 작업큐 / 워커 분리 / 서버 CORS·보안 / 경로 상대화 —
로컬 실행 모델에서는 불필요. 서버는 정적 배포 + 인증서 API만 담당.
