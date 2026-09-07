# Suno Helper 설치 안내 (v0.9.00)

## 설치 전 확인

- **Windows 10/11** (64bit)
- **Python 3.11 이상** — [python.org/downloads](https://www.python.org/downloads/)
  - 설치 시 **"Add python.exe to PATH" 반드시 체크**
- 인터넷 연결 (설치 시 패키지 다운로드)

## 설치 방법

1. 압축을 풀고 싶은 위치에 `SunoHelper` 폴더 전체를 둡니다.
   (예: `D:\SunoHelper` — 한글 경로도 가능하지만 영문 권장)
2. `install.bat`을 더블클릭합니다.
3. 자동 설치가 끝나면 바탕화면에 **"Suno Helper"** 바로가기가 생깁니다.

## 실행 / 종료

- **시작**: 바탕화면 `Suno Helper` (브라우저가 자동으로 열립니다)
- **종료**: 브라우저 탭을 닫으면 약 1~2분 후 서버도 자동 종료됩니다
  - 즉시 종료가 필요하면 바탕화면 `Suno Helper - Stop`
- 프로그램은 사용자 PC에서만 실행되고, 모든 데이터(음원·영상·DB)도 사용자 PC에 저장됩니다.

## 첫 실행 (라이선스 활성화)

1. [whick.org](https://whick.org) 로그인 → **Suno Helper → 내 PC 등록**
2. 발급받은 활성화 토큰(`sh_`로 시작)을 복사
3. 앱의 **설정 → 라이선스** 탭에 붙여넣고 **활성화** 클릭
4. 계정당 1대의 PC를 등록할 수 있습니다. (PC 교체는 웹에서 기기 해지 후 재등록)

## 필수 외부 프로그램

- **ffmpeg** (영상 인코딩) — 미설치 시 앱이 안내합니다.
  [ffmpeg.org](https://ffmpeg.org/download.html) 또는 `winget install ffmpeg`
- API 키: **OpenRouter** (AI 가사/프롬프트), **Google OAuth** (유튜브 업로드)
  → 앱의 **설정**에서 입력

## 문제 해결

| 증상 | 해결 |
|---|---|
| 백엔드 시작 실패 | `data\logs\backend.log` 확인 |
| 포트 충돌 (8765) | `stop.bat` 실행 후 재시작 |
| 한글 자막이 깨짐 | ffmpeg 최신 버전 설치 확인 |
| 라이선스 만료 | 설정 → 라이선스 → 지금 갱신 (온라인 필요) |

## 제거 방법

`stop.bat` 실행 후 폴더를 삭제하면 됩니다. 생성한 영상/데이터는 `data/` 폴더에 있으니
필요하면 미리 백업하세요 (설정 → 백업·복원에서 zip 백업 지원).
