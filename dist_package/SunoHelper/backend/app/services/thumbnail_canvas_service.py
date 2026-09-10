"""파워포인트형 썸네일 캔버스 — 배경 이미지 + 글상자 렌더."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

THUMB_W, THUMB_H = 1280, 720

# modern 템플릿 — playlist make_playlist_thumbnail 과 동일 좌표
MODERN_ART_X = 72
MODERN_ART_OUTER = 480 + 4 * 2 + 14 * 2  # 516
MODERN_TEXT_LEFT = MODERN_ART_X + MODERN_ART_OUTER + 48  # 636
MODERN_TEXT_MAX = THUMB_W - MODERN_TEXT_LEFT - 48
MODERN_DEFAULT_Y = 168
MODERN_FONT_TITLE = 52

BOX_PAD = 6
BOX_LINE_HEIGHT = 1.25

# 배경 렌더 캐시 (미리보기 속도)
_BG_LAYER_CACHE: dict[tuple, object] = {}
_BG_CACHE_MAX = 12
_MODERN_VIGNETTE = None

DEFAULT_BOX_STYLE = {
    "font_size": 36,
    "bold": True,
    "color": "#FFFFFF",
    "align": "left",
}


def _hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    c = (hex_color or "#FFFFFF").lstrip("#")
    if len(c) == 6:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        return r, g, b, alpha
    return 255, 255, 255, alpha


def _parse_rgba(value: str) -> tuple[int, int, int, int]:
    v = (value or "").strip()
    if v.startswith("rgba("):
        inner = v[5:-1]
        parts = [p.strip() for p in inner.split(",")]
        if len(parts) >= 4:
            r, g, b = int(float(parts[0])), int(float(parts[1])), int(float(parts[2]))
            a = int(float(parts[3]) * 255) if float(parts[3]) <= 1 else int(float(parts[3]))
            return r, g, b, a
    return _hex_to_rgba(v)


def _cover_crop(rgb, w: int, h: int):
    from PIL import Image

    cw, ch = rgb.size
    scale = max(w / cw, h / ch)
    bg_img = rgb.resize((int(cw * scale), int(ch * scale)), Image.LANCZOS)
    left = (bg_img.width - w) // 2
    top = (bg_img.height - h) // 2
    return bg_img.crop((left, top, left + w, top + h))


def _load_font(size: int, bold: bool):
    from app.services.playlist_pipeline_service import _load_thumb_font

    return _load_thumb_font(max(10, int(size)), bold=bold)


def _wrap_paragraph(draw, text: str, font, max_width: int) -> list[str]:
    words = (text or "").split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        bb = draw.textbbox((0, 0), trial, font=font)
        if bb[2] - bb[0] <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def _box_lines(draw, text: str, font, box_w: int) -> list[str]:
    """글상자 너비 기준 자동 줄바꿈 + 사용자 Enter(\\n) 유지."""
    pad = BOX_PAD
    max_w = max(20, box_w - pad * 2)
    out: list[str] = []
    for para in (text or "").split("\n"):
        if not para.strip():
            out.append("")
            continue
        out.extend(_wrap_paragraph(draw, para, font, max_w))
    return out or [""]


def _draw_box(draw, box: dict) -> None:
    x = int(box.get("x", 0))
    y = int(box.get("y", 0))
    w = int(box.get("w", 200))
    h = int(box.get("h", 60))
    fill = box.get("fill")
    if fill and str(box.get("text", "")).strip() == "":
        draw.rounded_rectangle([x, y, x + w, y + h], radius=6, fill=_parse_rgba(str(fill)))
        return
    if fill:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=6, fill=_parse_rgba(str(fill)))
    font_size = int(box.get("font_size", 36))
    bold = bool(box.get("bold", True))
    color = _hex_to_rgba(str(box.get("color", "#FFFFFF")))
    align = str(box.get("align", "left"))
    font = _load_font(font_size, bold)
    single_line = bool(box.get("single_line"))
    raw = str(box.get("text", ""))
    if single_line:
        lines = []
        for para in raw.split("\n"):
            line = para
            max_w = max(20, w - BOX_PAD * 2)
            while line and (draw.textbbox((0, 0), line, font=font)[2] - draw.textbbox((0, 0), line, font=font)[0]) > max_w:
                line = line[:-1]
            if line != para and len(line) > 1:
                line = line[:-1] + "…"
            lines.append(line)
    else:
        lines = _box_lines(draw, raw, font, w)
    pad = BOX_PAD
    # 사용자 Enter 줄바꿈이 있으면 박스 높이를 자동 확장 (잘림 방지)
    if "\n" in raw:
        total_h = pad * 2
        for line in lines:
            bb = draw.textbbox((0, 0), line or " ", font=font)
            total_h += (bb[3] - bb[1]) + max(2, int(font_size * (BOX_LINE_HEIGHT - 1.0)))
        h = max(h, total_h)
    cy = y + pad
    for line in lines:
        bb_line = draw.textbbox((0, 0), line or " ", font=font)
        line_h = bb_line[3] - bb_line[1]
        if cy + line_h > y + h - pad:
            break
        tw = bb_line[2] - bb_line[0]
        if align == "center":
            tx = x + (w - tw) // 2
        elif align == "right":
            tx = x + w - tw - pad
        else:
            tx = x + pad
        # 그림자
        draw.text((tx + 2, cy + 2), line, font=font, fill=(0, 0, 0, 160))
        draw.text((tx, cy), line, font=font, fill=color)
        gap = max(2, int(font_size * (BOX_LINE_HEIGHT - 1.0)))
        cy += line_h + gap


def _resolve_bg_image(project_dir: Path, bg: dict, assets: dict) -> Path | None:
    """배경 이미지 결정. 앨범 폴더·다른 트랙 경로도 허용."""
    from app.services.workflow_service import collect_album_images

    covers = assets.get("cover_image_paths") or [
        p for p in (assets.get("image_paths") or []) if not _is_generated_thumbnail(p)
    ]
    all_images = assets.get("image_paths") or []
    album_items = assets.get("album_images") or collect_album_images(project_dir)
    album_paths = [Path(it["path"] if isinstance(it, dict) else it) for it in album_items]

    name = str((bg or {}).get("image") or "").strip().replace("\\", "/")
    if name:
        raw = Path(name)
        candidates: list[Path] = []
        if raw.is_absolute():
            candidates.append(raw)
        candidates.extend(
            [
                project_dir / name,
                project_dir / raw.name,
                project_dir.parent / name,
                project_dir.parent / raw.name,
            ]
        )
        for it in album_items:
            if not isinstance(it, dict):
                candidates.append(Path(it))
                continue
            p = Path(it["path"])
            if (
                it.get("path") == name
                or str(it.get("path", "")).replace("\\", "/") == name
                or it.get("rel") == name
                or (it.get("name") or "").lower() == raw.name.lower()
            ):
                candidates.append(p)
        for p in candidates:
            try:
                if p.is_file():
                    return p
            except OSError:
                continue

    if covers:
        return Path(covers[0])
    if album_paths:
        return album_paths[0]
    return Path(all_images[0]) if all_images else None


def _modern_vignette_rgba(w: int, h: int):
    global _MODERN_VIGNETTE
    from PIL import Image, ImageDraw

    if _MODERN_VIGNETTE is None or _MODERN_VIGNETTE.size != (w, h):
        vignette = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        vd = ImageDraw.Draw(vignette)
        for i in range(90):
            a = int(90 * (i / 90) ** 1.4)
            vd.rectangle([i, i, w - 1 - i, h - 1 - i], outline=(0, 0, 0, a))
        _MODERN_VIGNETTE = vignette
    return _MODERN_VIGNETTE


def _bg_cache_get(key: tuple):
    return _BG_LAYER_CACHE.get(key)


def _bg_cache_put(key: tuple, img) -> None:
    if len(_BG_LAYER_CACHE) >= _BG_CACHE_MAX:
        _BG_LAYER_CACHE.pop(next(iter(_BG_LAYER_CACHE)))
    _BG_LAYER_CACHE[key] = img


def _render_background(canvas, cover_path: Path, bg: dict, *, fast: bool = False) -> None:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    mode = str((bg or {}).get("mode", "fill"))
    dim = float((bg or {}).get("dim", 0.35))
    w, h = THUMB_W, THUMB_H
    blur_r = 22 if fast else 32

    with Image.open(cover_path) as img:
        rgb = img.convert("RGB")
        cache_key = (str(cover_path), cover_path.stat().st_mtime_ns, mode, dim, fast)
        cached = _bg_cache_get(cache_key)
        if cached is not None:
            canvas.paste(cached.copy(), (0, 0))
            return

        if mode == "modern":
            scale = max(w / rgb.width, h / rgb.height) * 1.2
            bg_img = rgb.resize((int(rgb.width * scale), int(rgb.height * scale)), Image.LANCZOS)
            left = (bg_img.width - w) // 2
            top = (bg_img.height - h) // 2
            bg_img = bg_img.crop((left, top, left + w, top + h)).filter(ImageFilter.GaussianBlur(blur_r))
            bg_img = ImageEnhance.Brightness(bg_img).enhance(0.42).convert("RGBA")
            layer = Image.alpha_composite(bg_img, _modern_vignette_rgba(w, h))

            art_size = 480
            side = min(rgb.width, rgb.height)
            ox = (rgb.width - side) // 2
            oy = (rgb.height - side) // 2
            art = rgb.crop((ox, oy, ox + side, oy + side)).resize((art_size, art_size), Image.LANCZOS)
            white_b = 4
            mat_pad = 14
            outer = art_size + white_b * 2 + mat_pad * 2
            matte = Image.new("RGBA", (outer, outer), (32, 34, 40, 230))
            white = Image.new("RGBA", (art_size + white_b * 2, art_size + white_b * 2), (245, 245, 248, 255))
            white.paste(art.convert("RGBA"), (white_b, white_b))
            matte.paste(white, (mat_pad, mat_pad), white)
            art_x, art_y = 72, (h - outer) // 2
            if not fast:
                shadow = Image.new("RGBA", (outer + 48, outer + 48), (0, 0, 0, 0))
                ImageDraw.Draw(shadow).rounded_rectangle(
                    [10, 14, outer + 30, outer + 34],
                    radius=8,
                    fill=(0, 0, 0, 170),
                )
                shadow = shadow.filter(ImageFilter.GaussianBlur(16))
                layer.alpha_composite(shadow, (art_x - 14, art_y - 8))
            layer.paste(matte, (art_x, art_y), matte)
            _bg_cache_put(cache_key, layer)
            canvas.paste(layer.copy(), (0, 0))

        elif mode == "tpl-01-left-photo":
            left_w = w // 2
            canvas.paste(_cover_crop(rgb, left_w, h).convert("RGBA"), (0, 0))
            right_bg = ImageEnhance.Brightness(
                _cover_crop(rgb, left_w, h).filter(ImageFilter.GaussianBlur(28))
            ).enhance(0.35).convert("RGBA")
            canvas.paste(right_bg, (left_w, 0))
            ImageDraw.Draw(canvas).line([(left_w, 0), (left_w, h)], fill=(255, 255, 255, 40), width=2)

        elif mode == "tpl-06-bottom-bar":
            bar_h = int(h * 0.38)
            photo_h = h - bar_h
            canvas.paste(_cover_crop(rgb, w, photo_h).convert("RGBA"), (0, 0))
            ImageDraw.Draw(canvas).rectangle([0, photo_h, w, h], fill=(248, 248, 250, 255))

        elif mode == "tpl-07-polaroid":
            soft = ImageEnhance.Brightness(
                _cover_crop(rgb, w, h).filter(ImageFilter.GaussianBlur(24))
            ).enhance(0.55).convert("RGBA")
            canvas.paste(soft, (0, 0))

            pw, ph = 340, 380
            px = (w - pw) // 2
            py = 72
            side = min(rgb.width, rgb.height)
            ox = (rgb.width - side) // 2
            oy = (rgb.height - side) // 2
            art = rgb.crop((ox, oy, ox + side, oy + side)).resize((pw - 36, ph - 80), Image.LANCZOS)
            frame = Image.new("RGBA", (pw, ph), (252, 250, 246, 255))
            frame.paste(art.convert("RGBA"), (18, 18))
            shadow = Image.new("RGBA", (pw + 16, ph + 16), (0, 0, 0, 0))
            sh_draw = ImageDraw.Draw(shadow)
            sh_draw.rectangle([8, 8, pw + 8, ph + 8], fill=(0, 0, 0, 90))
            canvas.alpha_composite(shadow, (px - 8, py - 4))
            canvas.paste(frame, (px, py), frame)

        elif mode == "tpl-08-minimal":
            base = Image.new("RGBA", (w, h), (22, 22, 26, 255))
            faint = ImageEnhance.Brightness(
                _cover_crop(rgb, w, h).filter(ImageFilter.GaussianBlur(40))
            ).enhance(0.25).convert("RGBA")
            base.alpha_composite(faint)
            canvas.paste(base, (0, 0))

        else:
            canvas.paste(_cover_crop(rgb, w, h).convert("RGBA"), (0, 0))

        if dim > 0 and mode not in ("tpl-06-bottom-bar", "tpl-08-minimal", "modern"):
            overlay = Image.new("RGBA", (w, h), (0, 0, 0, int(min(220, dim * 255))))
            canvas.alpha_composite(overlay)


def _format_duration(sec: float | None) -> str:
    if not sec or sec <= 0:
        return ""
    total = int(round(sec))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _track_columns(track_names: list[str] | None) -> tuple[str, str]:
    names = [str(n).strip() for n in (track_names or []) if str(n).strip()]
    if not names:
        return "", ""
    mid = (len(names) + 1) // 2
    left = "\n".join(f"{i:02d}. {n}" for i, n in enumerate(names[:mid], 1))
    right = "\n".join(f"{i:02d}. {n}" for i, n in enumerate(names[mid:], mid + 1))
    return left, right


def _brand_footer_text() -> str:
    from app.services.brand_service import brand_footer_text

    return brand_footer_text()


def default_canvas_boxes(
    title: str,
    subtitle: str,
    track_count: int = 1,
    *,
    track_names: list[str] | None = None,
    duration_sec: float | None = None,
    meta_text: str | None = None,
) -> list[dict]:
    """참고 썸네일: FULL ALBUM / 제목 / 부제 / 메타 / © (트랙리스트 없음)."""
    names = [str(n).strip() for n in (track_names or []) if str(n).strip()]
    n = len(names) if names else max(1, int(track_count or 1))
    dur = _format_duration(duration_sec)
    if meta_text:
        meta = meta_text
    else:
        parts = ["가사 EN + KO", f"{n}곡"]
        if dur:
            parts.append(dur)
        meta = "  ·  ".join(parts)

    text_x = MODERN_TEXT_LEFT
    tw = MODERN_TEXT_MAX
    title_y = MODERN_DEFAULT_Y + 48
    sub_y = MODERN_DEFAULT_Y + 48 + MODERN_FONT_TITLE + 12
    meta_y = MODERN_DEFAULT_Y + 48 + MODERN_FONT_TITLE + 70
    return [
        {
            "id": "tag",
            "text": "FULL ALBUM",
            "x": text_x,
            "y": MODERN_DEFAULT_Y,
            "w": tw,
            "h": 36,
            "font_size": 24,
            "bold": True,
            "color": "#FFFFFF",
            "align": "left",
        },
        {
            "id": "title",
            "text": title or "Title",
            "x": text_x,
            "y": title_y,
            "w": tw,
            "h": 72,
            "font_size": MODERN_FONT_TITLE,
            "bold": True,
            "color": "#FFFFFF",
            "align": "left",
        },
        {
            "id": "sub",
            "text": subtitle or "",
            "x": text_x,
            "y": sub_y,
            "w": tw,
            "h": 56,
            "font_size": 30,
            "bold": True,
            "color": "#FFFFFF",
            "align": "left",
        },
        {
            "id": "meta",
            "text": meta,
            "x": text_x,
            "y": meta_y,
            "w": tw,
            "h": 40,
            "font_size": 22,
            "bold": False,
            "color": "#D2D2DA",
            "align": "left",
        },
        {
            "id": "footer",
            "text": _brand_footer_text(),
            "x": 440,
            "y": 678,
            "w": 400,
            "h": 28,
            "font_size": 14,
            "bold": False,
            "color": "#A0A0A8",
            "align": "center",
        },
    ]


def default_canvas_config(
    title: str,
    subtitle: str,
    image_name: str,
    track_count: int = 1,
    *,
    track_names: list[str] | None = None,
    duration_sec: float | None = None,
) -> dict:
    from app.services.thumbnail_templates import build_template_canvas

    return build_template_canvas(
        "tpl-modern",
        title,
        subtitle,
        image_name,
        track_count,
        track_names=track_names,
        duration_sec=duration_sec,
    )


def migrate_thumbnail_to_canvas(thumb: dict, assets: dict, project_dir: Path) -> dict:
    """레거시 positions/fonts → canvas 글상자."""
    if thumb.get("layout") == "canvas" and thumb.get("boxes"):
        return thumb

    title = thumb.get("title") or assets.get("track_title") or ""
    subtitle = thumb.get("subtitle") or ""
    images = assets.get("image_paths") or []
    image_name = Path(images[0]).name if images else ""
    # 생성본 thumbnail.jpg보다 원본 커버 우선
    for p in images:
        if Path(p).name.lower() != "thumbnail.jpg":
            image_name = Path(p).name
            break
    boxes = default_canvas_boxes(title, subtitle)
    pos = thumb.get("positions") or {}

    id_map = {"tag": "tag", "title": "title", "sub": "sub", "meta": "meta"}
    font_map = {
        "tag": thumb.get("font_tag", 24),
        "title": thumb.get("font_title", 52),
        "sub": thumb.get("font_sub", 32),
        "meta": thumb.get("font_meta", 22),
    }
    text_map = {
        "tag": "FULL ALBUM",
        "title": title,
        "sub": subtitle,
        "meta": boxes[3]["text"],
    }
    for box in boxes:
        bid = box["id"]
        p = pos.get(bid) or {}
        if p:
            box["x"] = int(p.get("x", box["x"]))
            box["y"] = int(p.get("y", box["y"]))
        box["font_size"] = int(font_map.get(bid, box["font_size"]))
        box["text"] = text_map.get(bid, box["text"])

    from app.services.thumbnail_templates import build_template_canvas

    out = build_template_canvas("tpl-modern", title, subtitle, image_name)
    out["title"] = title
    out["subtitle"] = subtitle
    return out


def render_thumbnail_canvas(
    project_dir: Path,
    canvas: dict,
    out_path: Path,
    *,
    assets: dict | None = None,
    preview_fast: bool = False,
) -> Path:
    from PIL import Image, ImageDraw

    assets = assets or {}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bg_cfg = canvas.get("background") or {}
    img_path = _resolve_bg_image(project_dir, bg_cfg, assets)
    if not img_path:
        raise ValueError("배경 이미지가 없습니다")

    base = Image.new("RGBA", (THUMB_W, THUMB_H), (20, 22, 28, 255))
    _render_background(base, img_path, bg_cfg, fast=preview_fast)

    draw = ImageDraw.Draw(base)
    for box in canvas.get("boxes") or []:
        has_fill = bool(box.get("fill"))
        has_text = bool(str(box.get("text", "")).strip())
        if has_text or has_fill or box.get("id") == "title":
            _draw_box(draw, box)

    quality = 88 if preview_fast else 94
    base.convert("RGB").save(out_path, "JPEG", quality=quality)
    return out_path


def new_text_box(x: int = 400, y: int = 300) -> dict:
    return {
        "id": f"box_{uuid.uuid4().hex[:8]}",
        "text": "텍스트",
        "x": x,
        "y": y,
        "w": 320,
        "h": 80,
        **DEFAULT_BOX_STYLE,
    }
