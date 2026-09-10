from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.database import init_db
from app.routers.extra import router as extra_router
from app.routers.pipeline import router as pipeline_router
from app.routers.editor import router as editor_router
from app.routers.youtube import router as youtube_router
from app.routers.license import router as license_router
from app.routers.local import router as local_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.config import settings
    from app.database import async_session
    from app.services.queue_service import resume_pending_album_jobs
    from app.services.pipeline_queue import resume_pending_pipeline_jobs
    from app.services.workflow_service import init_work_folders

    settings.data_dir.mkdir(exist_ok=True)
    (settings.data_dir / "uploads").mkdir(exist_ok=True)
    await init_db()
    try:
        async with async_session() as db:
            await init_work_folders(db)
            await db.commit()
    except Exception:
        pass
    await resume_pending_album_jobs()
    await resume_pending_pipeline_jobs()
    yield


app = FastAPI(
    title="Suno Helper",
    description="수노 음악 제작 도우미 - 가사, 프롬프트, 악기 세팅 생성",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def private_network_access(request, call_next):
    """Chrome Local Network Access(PNA) 대응.

    https://whick.org 같은 공개 사이트가 이 로컬 서버(127.0.0.1)를 fetch하면
    Chrome이 사전비행(Access-Control-Request-Private-Network)을 보내고,
    서버가 아래 헤더로 응답해야만 요청을 통과시킨다 (권한 deny 시 CORS 오류).
    """
    response = await call_next(request)
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

app.include_router(router, prefix="/api")
app.include_router(extra_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")
app.include_router(editor_router, prefix="/api")
app.include_router(youtube_router, prefix="/api")
app.include_router(license_router, prefix="/api")
app.include_router(local_router, prefix="/api")

@app.get("/api/health")
async def health():
    from app.services.update_service import APP_VERSION

    return {
        "status": "ok",
        "app": "Suno Helper",
        "version": APP_VERSION,
        "youtube": True,
        "prompt_engine": "compact-1000",
    }


@app.get("/api/version")
async def version_info():
    """업데이트 체널 — 현재 버전 + 새 버전 확인 (서버 미설정/오프라인 시 update: null)."""
    from app.services.update_service import check_for_update, current_version

    update = await check_for_update()
    return {"version": current_version(), "update": update}

# 프론트엔드 빌드 파일 서빙 (프로덕션)
# "/" 마운트는 미등록 POST /api/... 를 가로채 405를 낸다. /api 는 제외한다.
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    from starlette.staticfiles import StaticFiles as StarletteStaticFiles
    from starlette.types import Receive, Scope, Send

    class FrontendStatic(StarletteStaticFiles):
        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            path = scope.get("path") or ""
            if path == "/api" or path.startswith("/api/"):
                from starlette.responses import JSONResponse

                response = JSONResponse({"detail": "Not Found"}, status_code=404)
                await response(scope, receive, send)
                return
            await super().__call__(scope, receive, send)

    app.mount("/", FrontendStatic(directory=str(frontend_dist), html=True), name="static")
