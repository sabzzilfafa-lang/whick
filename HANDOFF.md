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

## Phase D — 앱 정리 (배포 품질)

1. **브랜드 기본값 초기화** — `DEFAULT_BRAND` 빈 값, "© WHICK Official" 폴백 2곳 제거
   (`playlist_pipeline_service.py` L178, `thumbnail_canvas_service.py`, `watermark_service.py` 기본 아이콘)
2. **i18n** — react-i18next 도입, `ko.json`/`en.json` (사이트 12개국어 중 ko/en 먼저, 페이지별 진행)
   백엔드 에러는 코드 기반(`FOLDER_NOT_FOUND` 등)으로 바꾸고 번역은 프론트에서
3. **폰트 폴백** — Noto Sans KR 번들 + `font_resolver.py` (Windows Malgun 우선, 없으면 번들) — 저비용 고장 방지
4. **requirements.txt 고정** — pip freeze 기준 핀 버전
5. 보류 항목 처리: Intel QSV/MF 인코딩 인자 분기 (감지돼도 libx264로 폴백되는 버그)

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
