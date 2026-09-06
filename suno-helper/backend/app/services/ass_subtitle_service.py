"""WHICK ASS 자막 SSOT — run_music_share_album.py 와 동일 좌표/크기."""

from __future__ import annotations

import re
from typing import Any


# Burned ASS (2560×1440) — Papa 확정 2026-08-27
ASS_W, ASS_H = 2560, 1440
ASS_SUB_MARGIN_LR = 80
ASS_FONT_TITLE = 70
ASS_FONT_LYRICS = 68
ASS_LYRICS_OUTLINE = 3
ASS_MV_TITLE = 55
ASS_MV_LYRICS_EN = 182  # EN (위)
ASS_MV_LYRICS_KO = 100  # KO (아래)
ASS_TITLE_INTRO_SEC = 6.0


def _cfg(config: dict | None) -> dict:
    return (config or {}).get("subtitle") or {}


def _video_play_res(config: dict | None) -> tuple[int, int, float, float]:
    """에디터·ASS 원본은 2560×1440. 실제 영상(기본 1920×1080)에 맞춰 PlayRes를 맞춤."""
    video = (config or {}).get("video") or {}
    out_w = int(video.get("width", 1920) or 1920)
    out_h = int(video.get("height", 1080) or 1080)
    sx = out_w / float(ASS_W)
    sy = out_h / float(ASS_H)
    return out_w, out_h, sx, sy


def _scaled_int(value: float, scale: float, *, minimum: int = 1) -> int:
    return max(minimum, int(round(float(value) * scale)))


def ass_play_res(config: dict | None = None) -> tuple[int, int]:
    s = _cfg(config)
    return int(s.get("play_res_x", ASS_W)), int(s.get("play_res_y", ASS_H))


def resolve_ass_font(config: dict | None = None) -> str:
    import os

    preferred = str(_cfg(config).get("font_name") or "").strip()
    if preferred and preferred not in ("Noto Serif CJK KR", "Noto Sans CJK KR"):
        return preferred
    if os.name == "nt":
        return "Malgun Gothic"
    return preferred or "Noto Sans CJK KR"


def fmt_ass_time(sec: float) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def safe_ass_text(text: str) -> str:
    return (
        (text or "")
        .replace("\n", " ")
        .replace("{", "(")
        .replace("}", ")")
    )


def clean_track_title(title: str) -> str:
    t = (title or "").strip()
    for _ in range(4):
        n = re.sub(r"^(?:track\s*)?\d{1,2}(?:\.\d+)?[.\s_\-]+", "", t, flags=re.I).strip()
        if n == t or not n:
            break
        t = n
    return t or (title or "").strip()


def hex_to_ass_color(value: str | None) -> str:
    raw = str(value or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return "&H00FFFFFF"
    try:
        r = int(raw[0:2], 16)
        g = int(raw[2:4], 16)
        b = int(raw[4:6], 16)
    except ValueError:
        return "&H00FFFFFF"
    return f"&H00{b:02X}{g:02X}{r:02X}"


def infer_album_and_track(project_dir) -> tuple[str, int | None]:
    from pathlib import Path

    p = Path(project_dir)
    album = p.parent.name if p.parent else ""
    m = re.match(r"^(\d{1,2})", p.name)
    idx = int(m.group(1)) if m else None
    return album, idx


def _subtitle_mode(config: dict | None) -> str:
    mode = str(_cfg(config).get("mode", "both")).lower()
    if mode in ("ko", "en", "both"):
        return mode
    return "both"


def _should_emit_en(mode: str) -> bool:
    return mode in ("en", "both")


def _should_emit_ko(mode: str) -> bool:
    return mode in ("ko", "both")


def build_whick_ass(
    *,
    track_title: str,
    duration_sec: float,
    cues: list[dict[str, Any]] | None,
    config: dict | None = None,
    album: str = "",
    track_index: int | None = None,
) -> str:
    """
    단곡 ASS:
      - 트랙 제목: 설정이 켜져 있으면 전 구간 표시 (미리보기와 동일)
      - 가사: EN 위 / KO 아래
    """
    s = _cfg(config)
    w, h, sx, sy = _video_play_res(config)
    font = resolve_ass_font(config)
    m = _scaled_int(s.get("margin_lr", ASS_SUB_MARGIN_LR), sx)
    fs_default = int(s.get("font_lyrics", ASS_FONT_LYRICS))
    fs_title = _scaled_int(s.get("font_title", ASS_FONT_TITLE), sy)
    fs_en = _scaled_int(s.get("font_lyrics_en", fs_default), sy)
    fs_ko = _scaled_int(s.get("font_lyrics_ko", fs_default), sy)
    outline = _scaled_int(s.get("lyrics_outline", ASS_LYRICS_OUTLINE), sy)
    y_title = _scaled_int(s.get("margin_v_title", ASS_MV_TITLE), sy, minimum=0)
    mv_en = _scaled_int(s.get("margin_v_lyrics_en", ASS_MV_LYRICS_EN), sy, minimum=0)
    mv_ko = _scaled_int(s.get("margin_v_lyrics_ko", ASS_MV_LYRICS_KO), sy, minimum=0)
    show_header = s.get("track_header_enabled", True)
    if isinstance(show_header, str):
        show_header = show_header.lower() not in ("0", "false", "off", "none")
    title_color = hex_to_ass_color(s.get("title_color") or "#FFFFFF")
    sub_mode = _subtitle_mode(config)

    cues = cues or []

    name = clean_track_title(track_title)
    if track_index is not None:
        title_text = f"Track {int(track_index):02d}. {name}"
        if album:
            title_text += f"  |  {album}"
    elif album:
        title_text = f"{name}  |  {album}"
    else:
        title_text = name

    cx = w // 2
    y_en = h - mv_en
    y_ko = h - mv_ko

    header = f"""[Script Info]
Title: Suno Helper / WHICK
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TitleCard,{font},{fs_title},{title_color},&H000000FF,&H80000000,&H90000000,1,0,0,0,100,100,0,0,1,2,3,8,{m},{m},{y_title},1
Style: LyricsEn,{font},{fs_en},&H00E8E8E8,&H000000FF,&H80000000,&H90000000,0,0,0,0,100,100,0,0,1,{outline},2,2,{m},{m},{mv_en},1
Style: LyricsKo,{font},{fs_ko},&H00FFFFFF,&H000000FF,&H80000000,&H90000000,1,0,0,0,100,100,0,0,1,{outline},3,2,{m},{m},{mv_ko},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    if show_header:
        title_end = max(float(duration_sec), 0.2)
        events.append(
            f"Dialogue: 1,0:00:00.00,{fmt_ass_time(title_end)},TitleCard,,0,0,0,,"
            f"{{\\an8\\pos({cx},{y_title})\\fad(400,0)}}{safe_ass_text(title_text)}"
        )

    for c in cues:
        st = float(c["start"])
        en_t = float(c["end"])
        if en_t <= st:
            continue
        en = safe_ass_text(str(c.get("en") or "").strip())
        ko = safe_ass_text(str(c.get("ko") or "").strip())
        if _should_emit_en(sub_mode) and en:
            events.append(
                f"Dialogue: 0,{fmt_ass_time(st)},{fmt_ass_time(en_t)},LyricsEn,,0,0,0,,"
                f"{{\\an2\\pos({cx},{y_en})\\fad(60,60)}}{en}"
            )
        if _should_emit_ko(sub_mode) and ko and (ko != en or not _should_emit_en(sub_mode)):
            events.append(
                f"Dialogue: 0,{fmt_ass_time(st)},{fmt_ass_time(en_t)},LyricsKo,,0,0,0,,"
                f"{{\\an2\\pos({cx},{y_ko})\\fad(60,60)}}{ko}"
            )

    return header + "\n".join(events) + "\n"


def build_whick_playlist_ass(
    tracks: list[dict[str, Any]],
    cues: list[dict[str, Any]] | None,
    config: dict | None = None,
    album: str = "",
) -> str:
    """합본: 곡마다 트랙 제목을 해당 구간 전체에 표시 + 절대시간 가사 큐."""
    s = _cfg(config)
    w, h, sx, sy = _video_play_res(config)
    font = resolve_ass_font(config)
    m = _scaled_int(s.get("margin_lr", ASS_SUB_MARGIN_LR), sx)
    fs_default = int(s.get("font_lyrics", ASS_FONT_LYRICS))
    fs_title = _scaled_int(s.get("font_title", ASS_FONT_TITLE), sy)
    fs_en = _scaled_int(s.get("font_lyrics_en", fs_default), sy)
    fs_ko = _scaled_int(s.get("font_lyrics_ko", fs_default), sy)
    outline = _scaled_int(s.get("lyrics_outline", ASS_LYRICS_OUTLINE), sy)
    y_title = _scaled_int(s.get("margin_v_title", ASS_MV_TITLE), sy, minimum=0)
    mv_en = _scaled_int(s.get("margin_v_lyrics_en", ASS_MV_LYRICS_EN), sy, minimum=0)
    mv_ko = _scaled_int(s.get("margin_v_lyrics_ko", ASS_MV_LYRICS_KO), sy, minimum=0)
    show_header = s.get("track_header_enabled", True)
    if isinstance(show_header, str):
        show_header = show_header.lower() not in ("0", "false", "off", "none")
    title_color = hex_to_ass_color(s.get("title_color") or "#FFFFFF")
    sub_mode = _subtitle_mode(config)

    cx = w // 2
    y_en = h - mv_en
    y_ko = h - mv_ko
    album_disp = (album or "").strip()

    header = f"""[Script Info]
Title: Suno Helper Playlist / WHICK
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TitleCard,{font},{fs_title},{title_color},&H000000FF,&H80000000,&H90000000,1,0,0,0,100,100,0,0,1,2,3,8,{m},{m},{y_title},1
Style: LyricsEn,{font},{fs_en},&H00E8E8E8,&H000000FF,&H80000000,&H90000000,0,0,0,0,100,100,0,0,1,{outline},2,2,{m},{m},{mv_en},1
Style: LyricsKo,{font},{fs_ko},&H00FFFFFF,&H000000FF,&H80000000,&H90000000,1,0,0,0,100,100,0,0,1,{outline},3,2,{m},{m},{mv_ko},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    cues = cues or []

    for t in tracks:
        t0 = float(t["start"])
        t1 = float(t["end"])
        if not show_header:
            continue
        name = clean_track_title(str(t.get("title") or ""))
        idx = int(t.get("num") or t.get("index") or 1)
        title_text = f"Track {idx:02d}. {name}" + (f"  |  {album_disp}" if album_disp else "")
        events.append(
            f"Dialogue: 1,{fmt_ass_time(t0)},{fmt_ass_time(t1)},TitleCard,,0,0,0,,"
            f"{{\\an8\\pos({cx},{y_title})\\fad(400,0)}}{safe_ass_text(title_text)}"
        )

    for c in cues:
        st = float(c["start"])
        en_t = float(c["end"])
        if en_t <= st:
            continue
        en = safe_ass_text(str(c.get("en") or "").strip())
        ko = safe_ass_text(str(c.get("ko") or "").strip())
        if _should_emit_en(sub_mode) and en:
            events.append(
                f"Dialogue: 0,{fmt_ass_time(st)},{fmt_ass_time(en_t)},LyricsEn,,0,0,0,,"
                f"{{\\an2\\pos({cx},{y_en})\\fad(60,60)}}{en}"
            )
        if _should_emit_ko(sub_mode) and ko and (ko != en or not _should_emit_en(sub_mode)):
            events.append(
                f"Dialogue: 0,{fmt_ass_time(st)},{fmt_ass_time(en_t)},LyricsKo,,0,0,0,,"
                f"{{\\an2\\pos({cx},{y_ko})\\fad(60,60)}}{ko}"
            )

    return header + "\n".join(events) + "\n"
