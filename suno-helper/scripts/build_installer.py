# -*- coding: utf-8 -*-
"""설치 패키지 빌드 — SunoHelper-Setup-{ver}.zip 생성.

포함: backend 소스 + 프론트 빌드본(dist) + installer(bat/매뉴얼) + scripts
제외: data/, logs, .venv, node_modules, __pycache__, .git, 개발 스크립트
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist_package"
STAGE = DIST / "SunoHelper"

# 버전은 update_service의 APP_VERSION과 동기화
sys.path.insert(0, str(ROOT / "backend"))
APP_VERSION = "1.0.0"  # app.services.update_service.APP_VERSION 값과 일치 유지

EXCLUDE_DIR_PARTS = {"__pycache__", ".venv", "node_modules", ".git", "logs", "dist_package", "wamss", ".pytest_cache", ".mypy_cache"}
EXCLUDE_FILES = {".env", "suno_helper.db", "_probe.py", "server_push.sh"}


def copy_tree(src: Path, dst: Path, top_level: bool = False) -> int:
    n = 0
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in EXCLUDE_FILES and top_level:
            continue
        if item.is_dir():
            if item.name in EXCLUDE_DIR_PARTS:
                continue
            n += copy_tree(item, dst / item.name)
        else:
            if item.suffix in {".pyc", ".pyo", ".log"}:
                continue
            shutil.copy2(item, dst / item.name)
            n += 1
    return n


def main() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    total = 0
    # 백엔드 소스
    total += copy_tree(ROOT / "backend" / "app", STAGE / "backend" / "app")
    for f in ["requirements.txt", "run_server.py"]:
        src = ROOT / "backend" / f
        if src.is_file():
            shutil.copy2(src, STAGE / "backend" / f)
            total += 1
    # 백엔드 assets (번들 폰트 등)
    assets = ROOT / "backend" / "app" / "assets"
    if not assets.exists():
        raise SystemExit("backend/app/assets 없음 — 폰트 번들 확인 필요")

    # 프론트 빌드본 (dist) — 반드시 사전에 npm run build
    dist = ROOT / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        raise SystemExit("frontend/dist/index.html 없음 — 먼저 npm run build 실행")
    total += copy_tree(dist, STAGE / "frontend" / "dist")

    # 최상위 실행 파일/문서
    for f in ["start.bat", "stop.bat", "MANUAL.md", "install.bat"]:
        # installer 우선, 없으면 루트 것 사용
        src = ROOT / "installer" / f
        if not src.is_file():
            src = ROOT / f
        if src.is_file():
            shutil.copy2(src, STAGE / f)
            total += 1

    # 서버 종료/포트 스크립트
    total += copy_tree(ROOT / "scripts", STAGE / "scripts")

    # .env.example
    ex = ROOT / ".env.example"
    if ex.is_file():
        shutil.copy2(ex, STAGE / ".env.example")
        total += 1

    # zip
    zip_path = DIST / f"SunoHelper-Setup-v{APP_VERSION}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in STAGE.rglob("*"):
            zf.write(p, p.relative_to(STAGE.parent))

    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"OK  {zip_path.name}  {size_mb:.1f} MB  ({total} files)")
    print(f"    stage: {STAGE}")


if __name__ == "__main__":
    main()
