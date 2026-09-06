"""영상 좌측 상단 채널 워터마크 — 브랜드 설정(이름·아이콘) 반영."""

from __future__ import annotations

from pathlib import Path

from app.services.brand_service import brand_icon_path, load_brand

# 구버전 호환용 상수 (참조하는 외부 코드 없음 — brand.json이 SSOT)
SOURCE_NAME = "whick-shellphone.jpg"
LABEL = ""
# 1920×1080 기준
WM_X = 36
WM_Y = 28
WM_ICON = 92


def source_icon_path() -> Path:
    """사용자 브랜드 아이콘. 배포 기본 아이콘은 넣지 않는다 (사용자가 업로드)."""
    return brand_icon_path()


def _watermark_label() -> str:
    b = load_brand()
    custom = (b.get("watermark_label") or "").strip()
    if custom:
        return custom
    return (b.get("channel_name") or "").strip()


def prepare_watermark_png(dest: Path, *, video_h: int = 1080) -> Path | None:
    """아이콘 + 글자를 투명 PNG로 만듦. 워터마크 끔/소스 없으면 None."""
    b = load_brand()
    if not b.get("watermark_enabled", True):
        return None
    src = source_icon_path()
    label = _watermark_label()
    if not src.is_file() and not label:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    scale = max(0.35, float(video_h) / 1080.0)
    icon_px = max(36, int(round(WM_ICON * scale)))
    gap = max(3, int(round(6 * scale)))
    font_px = max(11, int(round(17 * scale)))
    pad = max(2, int(round(2 * scale)))

    icon = None
    if src.is_file():
        try:
            raw = Image.open(src).convert("RGBA")
            icon = _cut_black_frame(raw)
            icon.thumbnail((icon_px, icon_px), Image.LANCZOS)
            icon_px = icon.width
        except OSError:
            icon = None
    if icon is None and not label:
        return None

    try:
        from app.services.font_resolver import pil_font

        font = pil_font(font_px, bold=True)
    except Exception:
        font = ImageFont.load_default()

    dummy = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    bb = dummy.textbbox((0, 0), label, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    w = max(icon_px if icon else 0, tw) + pad * 2
    top_pad = pad if icon is not None else pad * 2
    h = (icon.height if icon else 0) + (gap if icon is not None else 0) + th + pad * 2
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if icon is not None:
        ix = (w - icon.width) // 2
        canvas.paste(icon, (ix, top_pad), icon)
    draw = ImageDraw.Draw(canvas)
    tx = (w - tw) // 2 - bb[0]
    ty = top_pad + (icon.height if icon else 0) + (gap if icon is not None else 0) - bb[1]
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1)):
        draw.text((tx + dx, ty + dy), label, font=font, fill=(0, 0, 0, 160))
    draw.text((tx, ty), label, font=font, fill=(255, 255, 255, 245))
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, "PNG")
    return dest if dest.is_file() else None


def _cut_black_frame(im):
    from PIL import Image

    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if r < 22 and g < 22 and b < 22:
                px[x, y] = (0, 0, 0, 0)
    bbox = im.getbbox()
    if not bbox:
        return im
    cropped = im.crop(bbox)
    side = max(cropped.size)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(cropped, ((side - cropped.width) // 2, (side - cropped.height) // 2), cropped)
    return sq


def measure_watermark_size(video_h: int = 1080) -> tuple[int, int]:
    """렌더될 워터마크 PNG의 실제 크기 (px). 위치 계산용 — 파일 I/O 없는 근사."""
    scale = max(0.35, float(video_h) / 1080.0)
    icon_px = max(36, int(round(WM_ICON * scale)))
    font_px = max(11, int(round(17 * scale)))
    # 근사: 폰트 폭 ≈ 글자수 × 0.62 × font_px (맑은고딕 기준), 아이콘과 폰트 높이 합
    text_w = int(len(_watermark_label()) * font_px * 0.62)
    w = max(icon_px, text_w) + 4
    h = icon_px + max(3, int(round(6 * scale))) + font_px + 4
    return w, h


def watermark_xy(video_w: int, video_h: int) -> tuple[int, int]:
    """브랜드 설정(위치 프리셋 + 오프셋)을 따른다. 실패 시 기본 좌상단."""
    try:
        from app.services.brand_service import brand_watermark_xy

        return brand_watermark_xy(video_w, video_h)
    except Exception:
        sx = video_w / 1920.0
        sy = video_h / 1080.0
        return max(8, int(round(WM_X * sx))), max(8, int(round(WM_Y * sy)))


def watermark_overlay_fc(
    main: str,
    wm_in: str,
    out: str,
    *,
    x: int,
    y: int,
    yuv: bool = True,
) -> str:
    tail = ",format=yuv420p" if yuv else ""
    return f"{wm_in}format=rgba[wm];{main}[wm]overlay=x={x}:y={y}:format=auto{tail}[{out}]"
