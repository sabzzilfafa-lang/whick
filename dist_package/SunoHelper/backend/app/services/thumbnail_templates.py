"""썸네일 풀 템플릿 — 배경 레이아웃 + 글상자 프리셋."""

from __future__ import annotations

from typing import Any

THUMB_W, THUMB_H = 1280, 720

TEMPLATE_IDS = (
    "tpl-modern",
    "tpl-01-left-photo",
    "tpl-02-full-center",
    "tpl-03-top-bottom",
    "tpl-04-center-card",
    "tpl-05-stacked",
    "tpl-06-bottom-bar",
    "tpl-07-polaroid",
    "tpl-08-minimal",
)

TEMPLATE_LABELS: dict[str, str] = {
    "tpl-modern": "기본 · 전체 블러 + 좌측 앨범 + 우측 타이포",
    "tpl-01-left-photo": "① 좌측 사진 + 우측 타이포",
    "tpl-02-full-center": "② 사진 전체 + 중앙 대형 타이틀",
    "tpl-03-top-bottom": "③ 좌상단 소제목 + 하단 대형 제목",
    "tpl-04-center-card": "④ 중앙 세로 박스형",
    "tpl-05-stacked": "⑤ 대형 제목 겹침",
    "tpl-06-bottom-bar": "⑥ 사진 + 하단 흰색 타이틀",
    "tpl-07-polaroid": "⑦ 폴라로이드 / 사진첩",
    "tpl-08-minimal": "⑧ 미니멀 타이포",
}


def _meta_text(track_count: int) -> str:
    return f"Instrumental • {track_count}곡" if track_count > 1 else "Instrumental"


def _boxes_for_template(
    template_id: str,
    title: str,
    subtitle: str,
    track_count: int = 1,
    *,
    track_names: list[str] | None = None,
    duration_sec: float | None = None,
) -> list[dict[str, Any]]:
    t = title or "Title"
    s = subtitle or ""
    meta = _meta_text(track_count)

    if template_id == "tpl-modern":
        from app.services.thumbnail_canvas_service import default_canvas_boxes

        return default_canvas_boxes(
            title,
            subtitle,
            track_count,
            track_names=track_names,
            duration_sec=duration_sec,
        )

    if template_id == "tpl-01-left-photo":
        return [
            {
                "id": "title",
                "text": t,
                "x": 660,
                "y": 190,
                "w": 580,
                "h": 200,
                "font_size": 56,
                "bold": True,
                "color": "#FFFFFF",
                "align": "left",
            },
            {
                "id": "sub",
                "text": s or "autumn pop\nplaylist",
                "x": 660,
                "y": 400,
                "w": 580,
                "h": 100,
                "font_size": 30,
                "bold": False,
                "color": "#E8E0D4",
                "align": "left",
            },
        ]

    if template_id == "tpl-02-full-center":
        return [
            {
                "id": "title",
                "text": t,
                "x": 140,
                "y": 250,
                "w": 1000,
                "h": 120,
                "font_size": 64,
                "bold": True,
                "color": "#FFFFFF",
                "align": "center",
            },
            {
                "id": "line",
                "text": "───────────────",
                "x": 140,
                "y": 370,
                "w": 1000,
                "h": 36,
                "font_size": 22,
                "bold": False,
                "color": "#D8C8A8",
                "align": "center",
            },
            {
                "id": "sub",
                "text": (s or "AUTUMN PLAYLIST").upper(),
                "x": 140,
                "y": 410,
                "w": 1000,
                "h": 60,
                "font_size": 30,
                "bold": False,
                "color": "#F0EDE8",
                "align": "center",
            },
        ]

    if template_id == "tpl-03-top-bottom":
        return [
            {
                "id": "tag",
                "text": (s or "AUTUMN PLAYLIST").upper(),
                "x": 56,
                "y": 44,
                "w": 560,
                "h": 44,
                "font_size": 26,
                "bold": True,
                "color": "#FFFFFF",
                "align": "left",
            },
            {
                "id": "title",
                "text": t,
                "x": 56,
                "y": 500,
                "w": 760,
                "h": 180,
                "font_size": 58,
                "bold": True,
                "color": "#FFFFFF",
                "align": "left",
            },
        ]

    if template_id == "tpl-04-center-card":
        return [
            {
                "id": "card",
                "text": "",
                "x": 380,
                "y": 175,
                "w": 520,
                "h": 370,
                "font_size": 1,
                "bold": False,
                "color": "#FFFFFF",
                "align": "center",
                "fill": "rgba(0,0,0,0.58)",
            },
            {
                "id": "title",
                "text": t,
                "x": 410,
                "y": 230,
                "w": 460,
                "h": 140,
                "font_size": 50,
                "bold": True,
                "color": "#FFFFFF",
                "align": "center",
            },
            {
                "id": "sub",
                "text": (s or "AUTUMN POP").upper(),
                "x": 410,
                "y": 390,
                "w": 460,
                "h": 80,
                "font_size": 28,
                "bold": False,
                "color": "#E0D8CC",
                "align": "center",
            },
        ]

    if template_id == "tpl-05-stacked":
        return [
            {
                "id": "title",
                "text": t,
                "x": 40,
                "y": 260,
                "w": 620,
                "h": 320,
                "font_size": 76,
                "bold": True,
                "color": "#FFFFFF",
                "align": "left",
            },
            {
                "id": "meta",
                "text": meta if track_count > 1 else (s or "AUTUMN 2026").upper(),
                "x": 640,
                "y": 620,
                "w": 600,
                "h": 56,
                "font_size": 30,
                "bold": False,
                "color": "#F5F0E8",
                "align": "right",
            },
        ]

    if template_id == "tpl-06-bottom-bar":
        return [
            {
                "id": "title",
                "text": t,
                "x": 48,
                "y": 548,
                "w": 1184,
                "h": 72,
                "font_size": 46,
                "bold": True,
                "color": "#1A1A1E",
                "align": "left",
            },
            {
                "id": "meta",
                "text": s or f"Autumn Pop · {meta}",
                "x": 48,
                "y": 628,
                "w": 1184,
                "h": 48,
                "font_size": 24,
                "bold": False,
                "color": "#4A4A52",
                "align": "left",
            },
        ]

    if template_id == "tpl-07-polaroid":
        return [
            {
                "id": "title",
                "text": t,
                "x": 160,
                "y": 510,
                "w": 960,
                "h": 80,
                "font_size": 44,
                "bold": True,
                "color": "#FFFFFF",
                "align": "center",
            },
            {
                "id": "sub",
                "text": s or "autumn playlist",
                "x": 160,
                "y": 595,
                "w": 960,
                "h": 50,
                "font_size": 28,
                "bold": False,
                "color": "#E8E4DC",
                "align": "center",
            },
        ]

    if template_id == "tpl-08-minimal":
        return [
            {
                "id": "title",
                "text": t,
                "x": 420,
                "y": 200,
                "w": 440,
                "h": 210,
                "font_size": 54,
                "bold": True,
                "color": "#FFFFFF",
                "align": "center",
            },
            {
                "id": "line",
                "text": "─────",
                "x": 420,
                "y": 420,
                "w": 440,
                "h": 32,
                "font_size": 20,
                "bold": False,
                "color": "#C8B890",
                "align": "center",
            },
            {
                "id": "sub",
                "text": (s or "AUTUMN\nPLAYLIST").upper(),
                "x": 420,
                "y": 460,
                "w": 440,
                "h": 110,
                "font_size": 32,
                "bold": False,
                "color": "#D8D4CC",
                "align": "center",
            },
        ]

    # fallback
    from app.services.thumbnail_canvas_service import default_canvas_boxes

    return default_canvas_boxes(title, subtitle, track_count)


def _background_for_template(template_id: str) -> dict[str, Any]:
    # tpl-modern uses legacy renderer mode "modern"
    dims = {
        "tpl-modern": 0.0,
        "tpl-01-left-photo": 0.15,
        "tpl-02-full-center": 0.45,
        "tpl-03-top-bottom": 0.3,
        "tpl-04-center-card": 0.5,
        "tpl-05-stacked": 0.35,
        "tpl-06-bottom-bar": 0.0,
        "tpl-07-polaroid": 0.2,
        "tpl-08-minimal": 0.65,
    }
    mode = "modern" if template_id == "tpl-modern" else template_id
    return {"mode": mode, "dim": dims.get(template_id, 0.3)}


def build_template_canvas(
    template_id: str,
    title: str,
    subtitle: str,
    image_name: str,
    track_count: int = 1,
    *,
    track_names: list[str] | None = None,
    duration_sec: float | None = None,
) -> dict[str, Any]:
    tid = template_id if template_id in TEMPLATE_IDS else "tpl-modern"
    bg = _background_for_template(tid)
    bg["image"] = image_name
    n = len(track_names) if track_names else track_count
    return {
        "layout": "canvas",
        "template_id": tid,
        "title": title,
        "subtitle": subtitle,
        "background": bg,
        "boxes": _boxes_for_template(
            tid,
            title,
            subtitle,
            n,
            track_names=track_names,
            duration_sec=duration_sec,
        ),
    }


def apply_template_to_canvas(
    canvas: dict,
    template_id: str,
    *,
    track_count: int = 1,
    track_names: list[str] | None = None,
    duration_sec: float | None = None,
) -> dict:
    """기존 제목/부제 텍스트를 유지한 채 템플릿 레이아웃 적용."""
    title = canvas.get("title") or ""
    subtitle = canvas.get("subtitle") or ""
    boxes = canvas.get("boxes") or []
    for b in boxes:
        if b.get("id") == "title" and b.get("text"):
            title = b["text"]
        if b.get("id") in ("sub", "subtitle") and b.get("text"):
            subtitle = b["text"]
    image_name = (canvas.get("background") or {}).get("image") or ""
    out = build_template_canvas(
        template_id,
        title,
        subtitle,
        image_name,
        track_count,
        track_names=track_names,
        duration_sec=duration_sec,
    )
    out["title"] = title
    out["subtitle"] = subtitle
    return out
