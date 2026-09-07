from contextlib import asynccontextmanager
import asyncio
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.database import init_db
from app.routers.extra import router as extra_router
from app.routers.pipeline import router as pipeline_router
from app.routers.editor import router as editor_router
from app.routers.license import router as license_router
from app.routers.local import router as local_router
from app.routers.youtube import router as youtube_router


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
    # 라이선스 자동 갱신 (만료 7일 전, 온라인일 때만 — 실패 무시)
    try:
        from app.services.license_service import maybe_auto_renew

        await maybe_auto_renew()
    except Exception:
        pass
    # 브라우저 닫힘 감지 자동 종료 (하트비트 방식 — 헤드리스/오류 시 무해)
    if os.environ.get("SUNO_AUTO_STOP", "1") != "0":
        _start_auto_stop_watcher()
    yield
    _cancel_auto_stop_watcher()


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
async def allow_private_network(request, call_next):
    """Chrome PNA: 공개 HTTPS(whick.org) → 로컬(127.0.0.1) 요청 프리플라이트 허용."""
    response = await call_next(request)
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response

app.include_router(router, prefix="/api")
app.include_router(extra_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")
app.include_router(editor_router, prefix="/api")
app.include_router(license_router, prefix="/api")
app.include_router(local_router, prefix="/api")
app.include_router(youtube_router, prefix="/api")

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


# ---- 브라우저 닫힘 감지 자동 종료 ----
# 프론트가 /api/heartbeat를 15초 간격으로 호출. 마지막 호출 후 90초 경과 시 종료.
# OS 종료·절전·네트워크 지연 대비 그레이스를 넉넉히 둠. 수동 서버 운영은 SUNO_AUTO_STOP=0으로 끌 수 있음.
AUTO_STOP_TIMEOUT_SEC = 90
_last_heartbeat: list[float] = [0.0]
_auto_stop_task: list[asyncio.Task | None] = [None]


async def _auto_stop_watcher() -> None:
    import time

    while True:
        await asyncio.sleep(10)
        last = _last_heartbeat[0]
        if last <= 0:
            continue  # 아직 브라우저가 열리지 않음 (설치 직후 등)
        import time as _t

        if _t.time() - last > AUTO_STOP_TIMEOUT_SEC:
            from app.services.update_service import APP_VERSION

            import logging

            logging.getLogger("uvicorn.error").info(
                "브라우저 연결이 끊겨 서버를 자동 종료합니다 (Suno Helper %s)",
                APP_VERSION,
            )
            os._exit(0)


def _start_auto_stop_watcher() -> None:
    _auto_stop_task[0] = asyncio.ensure_future(_auto_stop_watcher())


def _cancel_auto_stop_watcher() -> None:
    if _auto_stop_task[0]:
        _auto_stop_task[0].cancel()


@app.post("/api/heartbeat")
async def heartbeat():
    import time

    _last_heartbeat[0] = time.time()
    return {"ok": True}


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
