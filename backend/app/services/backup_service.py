import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from app.config import settings


def export_backup() -> Path:
    data_dir = settings.data_dir
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = backup_dir / f"suno_helper_backup_{timestamp}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        db_file = data_dir / "suno_helper.db"
        if db_file.exists():
            zf.write(db_file, "suno_helper.db")

        # 사용자 설정 파일들 (브랜드·스타일·프리셋·에디터 기본)
        for cfg_name in ("brand.json", "editor_user_style.json", "editor_style_presets.json"):
            cfg_file = data_dir / cfg_name
            if cfg_file.exists():
                zf.write(cfg_file, cfg_name)

        brand_icon = data_dir / "assets" / "brand_icon.png"
        if brand_icon.exists():
            zf.write(brand_icon, "assets/brand_icon.png")

        uploads = data_dir / "uploads"
        if uploads.exists():
            for f in uploads.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(data_dir).as_posix())

    return zip_path


def import_backup(zip_path: Path) -> dict:
    data_dir = settings.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    restored_db = False
    restored_files = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            target = data_dir / name
            if name == "suno_helper.db":
                if target.exists():
                    backup = data_dir / f"suno_helper.db.bak_{datetime.now().strftime('%H%M%S')}"
                    shutil.copy2(target, backup)
                zf.extract(name, data_dir)
                restored_db = True
            elif name.startswith("uploads/") or name in (
                "brand.json",
                "editor_user_style.json",
                "editor_style_presets.json",
            ) or name == "assets/brand_icon.png":
                target.parent.mkdir(parents=True, exist_ok=True)
                zf.extract(name, data_dir)
                restored_files += 1

    return {
        "restored_db": restored_db,
        "restored_files": restored_files,
        "message": "백업 복원 완료. 서버를 재시작하면 적용됩니다.",
    }
