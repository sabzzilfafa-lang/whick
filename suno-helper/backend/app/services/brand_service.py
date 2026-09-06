"""채널 브랜드 설정 — 배포용: 사용자별 채널 이름·아이콘·기본 태그를 저장하고
자동 생성물(설명 자동 블록·기본 태그·해시태그·영상 워터마크·썸네일 푸터)에 반영한다.

저장 위치: data/brand.json (기기별 사용자 설정 — 프로그램 기본값이 아님)
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.config import settings

BRAND_FILE = "brand.json"
_ICON_NAME = "brand_icon"

# 프로그램 출고 기본값 — 배포용: 모두 비어 있어 자동 생성물(설명 블록·워터마크·썸네일 푸터)
# 에 브랜드 문구가 들어가지 않는다. 사용자가 설정에서 채우면 그 값이 우선한다.
DEFAULT_BRAND: dict[str, Any] = {
    "channel_name": "",
    "source_url": "",
    "copyright_line": "",
    "default_tags": [],
    "default_hashtags": "",
    # 워터마크: 채널 아이콘+이름 표시 (끄면 워터마크 자체를 넣지 않음)
    "watermark_enabled": True,
    "watermark_label": "",
    # 위치 — 1920×1080 기준 픽셀 / preset: top_left·top_right·bottom_left·bottom_right·custom
    "watermark_pos": "top_left",
    "watermark_x": 36,
    "watermark_y": 28,
    # 썸네일 푸터 자동 채움 (끄면 사용자가 캔버스에서 직접 관리)
    "footer_enabled": True,
    # 유튜브 설명 자동 블록 구성 (위젯) — 블록 id 목록. 비어 있으면 기본 구성 사용
    "desc_blocks": ["album_title", "intro", "tracklist", "specs", "copyright", "hashtags"],
    # 자유 블록 내용 — desc_blocks에 "custom"이 있을 때 설명에 들어감
    "custom_desc_block": "",
}

_brand_path_cache: dict[str, Path] = {}


def brand_path() -> Path:
    d = settings.data_dir
    d.mkdir(parents=True, exist_ok=True)
    return d / BRAND_FILE


def brand_icon_path() -> Path:
    d = settings.data_dir
    d.mkdir(parents=True, exist_ok=True)
    return d / "assets" / f"{_ICON_NAME}.png"


def load_brand() -> dict[str, Any]:
    """brand.json + 출고 기본값 병합. 사용자 저장값이 항상 우선."""
    data: dict[str, Any] = {}
    p = brand_path()
    if p.is_file():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (json.JSONDecodeError, OSError):
            data = {}
    merged = dict(DEFAULT_BRAND)
    merged.update(data)
    return merged


def save_brand(updates: dict[str, Any]) -> dict[str, Any]:
    """부분 업데이트 — 전달된 키만 덮어쓴다."""
    current = load_brand()
    allowed = set(DEFAULT_BRAND.keys())
    for k, v in updates.items():
        if k in allowed:
            current[k] = v
    brand_path().write_text(
        json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return current


def save_brand_icon(src: Path) -> Path:
    """업로드된 아이콘을 data/assets/brand_icon.png 로 복사."""
    dest = brand_icon_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    # PIL로 열어 검증 후 PNG로 통일 저장 (손상 파일 방지)
    from PIL import Image

    with Image.open(src) as im:
        im.convert("RGBA").save(dest, "PNG")
    return dest


def reset_brand_icon() -> bool:
    """아이콘 삭제 — 워터마크는 글자만 표시."""
    p = brand_icon_path()
    if p.is_file():
        p.unlink()
        return True
    return False


def brand_display_name() -> str:
    return (load_brand().get("channel_name") or "").strip()


def brand_hashtag_defaults() -> tuple[list[str], str]:
    b = load_brand()
    tags = list(b.get("default_tags") or [])
    tags = [t.strip() for t in tags if str(t).strip()]
    hashtags = (b.get("default_hashtags") or "").strip()
    return tags, hashtags


def brand_footer_text() -> str:
    b = load_brand()
    if not b.get("footer_enabled", True):
        return ""
    return (b.get("copyright_line") or "").strip()


def brand_source_url() -> str:
    return (load_brand().get("source_url") or "").strip()


def brand_watermark_xy(video_w: int, video_h: int) -> tuple[int, int]:
    """브랜드 워터마크 위치 — preset + 사용자 오프셋(x/y, 1920×1080 기준 스케일)."""
    b = load_brand()
    pos = str(b.get("watermark_pos") or "top_left")
    ux = int(b.get("watermark_x") or 0)
    uy = int(b.get("watermark_y") or 0)
    sx = video_w / 1920.0
    sy = video_h / 1080.0
    if pos == "top_right":
        from app.services.watermark_service import measure_watermark_size

        mw, mh = measure_watermark_size(video_h)
        x = max(8, video_w - mw - max(8, int(round(ux * sx))))
        y = max(8, int(round(uy * sy)) if uy else 28)
        return x, y
    if pos == "bottom_left":
        mw, mh = measure_watermark_size(video_h)
        x = max(8, int(round(ux * sx)) if ux else 36)
        y = max(8, video_h - mh - max(8, int(round(abs(uy) * sy)) if uy else 28))
        return x, y
    if pos == "bottom_right":
        mw, mh = measure_watermark_size(video_h)
        x = max(8, video_w - mw - max(8, int(round(abs(ux) * sx)) if ux else 36))
        y = max(8, video_h - mh - max(8, int(round(abs(uy) * sy)) if uy else 28))
        return x, y
    # top_left (기본) 또는 custom
    x = max(8, int(round(ux * sx)) if ux else 36)
    y = max(8, int(round(uy * sy)) if uy else 28)
    return x, y


def new_icon_token() -> str:
    """아이콘 캐시 무효화용 토큰."""
    return uuid.uuid4().hex[:8]
