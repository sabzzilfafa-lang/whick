from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.database import init_db
from app.routers.extra import router as extra_router
from app.routers.pipeline import router as pipeline_router
from app.routers.youtube import router as youtube_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.config import settings
    from app.database import async_session
    from app.services.queue_service import resume_pending_album_jobs
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

app.include_router(router, prefix="/api")
app.include_router(extra_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")
app.include_router(youtube_router, prefix="/api")

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "app": "Suno Helper",
        "youtube": True,
        "prompt_engine": "compact-1000",
    }

# 프론트엔드 빌드 파일 서빙 (프로덕션)
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")
