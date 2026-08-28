# Suno Helper - 수노 음악 제작 도우미

OpenRouter의 여러 AI를 활용해 **일관된 스타일**의 수노 가사, 프롬프트, 악기 세팅을 생성하는 로컬 데스크탑 앱입니다.  
웹 브라우저에서 `http://localhost:5173` 으로 접속해 사용합니다.

## 주요 기능

- **음악 프로필** — 장르, 분위기, 템포, 악기 등 취향을 단계별로 설정·저장
- **앨범 기획** — 컨셉, 분위기, 곡 수, 목표 시간 단위 관리
- **AI 생성** — OpenRouter로 가사 / Suno 프롬프트 / 악기 세팅 (작업별 모델 분리)
- **일괄 생성** — 앨범 전체 트랙을 컨셉에 맞게 자동 생성
- **유사 곡 생성** — 기존 곡을 참조해 같은 분위기의 새 곡 생성
- **로컬 저장** — 가사, 프롬프트, 음원 파일을 SQLite + 로컬 폴더에 보관

## 시작하기

### 요구 사항

- Python 3.11+
- Node.js 18+
- [OpenRouter API 키](https://openrouter.ai/keys)

### 실행

```bash
# Windows
start.bat

# 또는 수동 실행
# 1. 백엔드
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cd ..
copy .env.example .env   # API 키 설정
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload --app-dir backend

# 2. 프론트엔드 (새 터미널)
cd frontend
npm install
npm run dev
```

브라우저에서 http://127.0.0.1:5173 접속

### 환경 변수 (.env) — 선택사항

API 키는 **사용자 설정** 화면에서 입력하는 것을 권장합니다. `.env`는 폴백용입니다.

```env
OPENROUTER_API_KEY=
```

### 지원 AI 제공업체

| 제공업체 | 설명 |
|---------|------|
| **OpenRouter** | 여러 모델을 하나의 API로 |
| **OpenAI** | GPT-4o 등 직접 연동 |
| **Anthropic** | Claude 시리즈 직접 연동 |
| **Google Gemini** | Gemini 시리즈 직접 연동 |

작업별(가사/프롬프트/악기/분석)로 서로 다른 제공업체를 조합할 수 있습니다.

## 프로젝트 구조

```
suno_helper/
├── backend/           # FastAPI + SQLite
│   └── app/
│       ├── api.py         # REST API
│       ├── models.py      # DB 모델
│       └── services/      # OpenRouter AI 연동
├── frontend/          # React + Vite
│   └── src/
│       ├── pages/         # 홈, 앨범, 곡, 프로필
│       └── api.ts         # API 클라이언트
├── data/              # DB 및 업로드 파일 (로컬)
├── start.bat          # 원클릭 실행
└── .env.example
```

## 사용 흐름

1. **음악 프로필** 생성 → 장르·분위기·악기 등 취향 저장
2. **앨범** 생성 → 컨셉, 곡 수, 프로필 연결
3. **전체 곡 일괄 생성** 또는 개별 곡 편집
4. 곡별로 **가사 → 프롬프트 → 악기** 순서로 AI 생성
5. 수노에 복사해 사용, 완성 음원은 **업로드**로 보관
6. 마음에 드는 곡 기준 **유사 곡** 추가 생성

## 추가 기능 제안

현재 MVP에 더하면 좋을 기능들입니다.

| 기능 | 설명 |
|------|------|
| **버전 히스토리** | 가사/프롬프트 수정 이력, 이전 버전 복원 |
| **A/B 비교** | 같은 곡에 여러 AI 결과를 나란히 비교 후 선택 |
| **Suno 원클릭 복사** | 가사+프롬프트를 클립보드에 포맷 맞춰 복사 |
| **프리셋 템플릿** | 장르별 기본 프로필 (K-Pop, Lo-fi 등) |
| **백업/복원** | `data/` 폴더 전체보내기·가져오기 |
| **검색** | 앨범·곡·가사 전체 검색 |
| **태그 시스템** | 곡별 태그로 필터링·그룹핑 |
| **생성 큐** | 여러 곡 배치 생성 시 진행률 표시 |
| **설정 페이지** | AI 모델 선택, temperature 등 UI에서 조정 |
| **앨범 커버** | 이미지 업로드로 앨범 시각화 |

## 라이선스

MIT
