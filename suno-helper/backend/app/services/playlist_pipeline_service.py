"""앨범/다중 곡 합본 영상 파이프라인 — WHICK playlist-music-share 로직 이식."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.pipeline_defaults import get_default_config
from app.services.pipeline_service import (
    _audio_mux_args,
    _eq_overlay_fc,
    _run,
    _video_encode_args,
    build_subtitles_vf,
    detect_video_encoder,
    find_ffmpeg,
    make_cover_frame,
    probe_duration,
    remaster_audio,
)
from app.services.watermark_service import (
    prepare_watermark_png,
    watermark_overlay_fc,
    watermark_xy,
)
from app.services.workflow_service import (
    find_project_assets,
    pick_album_fallback_cover,
    pick_track_playlist_cover,
    remember_pipeline_output,
)


WHICK_SOURCE_URL = ""  # deprecated — brand_service.brand_source_url() 사용


def fmt_chapter_ts(sec: float) -> str:
    """YouTube 챕터용 타임스탬프 (0:00 / 1:23:45)."""
    total = max(0, int(round(float(sec or 0))))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def captions_label(subtitle_mode: str | None) -> str:
    mode = (subtitle_mode or "both").lower()
    if mode == "en":
        return "English lyrics (on-screen)"
    if mode == "ko":
        return "Korean lyrics (on-screen)"
    return "English lyrics + Korean translation (on-screen)"


def _track_start(track: dict[str, Any]) -> float:
    return float(track.get("start") or track.get("start_sec") or 0)


def _track_duration(track: dict[str, Any]) -> float:
    if track.get("duration") is not None:
        return float(track["duration"])
    if track.get("duration_sec") is not None:
        return float(track["duration_sec"])
    start = _track_start(track)
    end = track.get("end")
    if end is not None:
        return max(0.0, float(end) - start)
    return 0.0


def playlist_runtime_sec(tracks: list[dict[str, Any]]) -> float:
    if not tracks:
        return 0.0
    last = tracks[-1]
    dur = _track_duration(last)
    if dur > 0:
        return _track_start(last) + dur
    total = sum(_track_duration(t) for t in tracks)
    if total > 0:
        return total
    return _track_start(last)


def _display_title(title: str) -> str:
    t = (title or "").strip()
    if t.startswith("【") and t.endswith("】"):
        return t
    return f"【{t}】" if t else "【Playlist】"


def _plain_heading(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("【") and t.endswith("】"):
        t = t[1:-1].strip()
    return " ".join(t.lower().split())


def _same_block(a: str, b: str) -> bool:
    na, nb = _plain_heading(a), _plain_heading(b)
    return bool(na and nb and na == nb)


def _uniq_intro_blocks(*chunks: str) -> list[str]:
    out: list[str] = []
    for raw in chunks:
        t = (raw or "").strip()
        if not t:
            continue
        if any(_same_block(t, prev) for prev in out):
            continue
        out.append(t)
    return out


def _safe_ass_text(text: str) -> str:
    return text.replace("\n", " ").replace("{", "(").replace("}", ")")


def build_playlist_ass(
    tracks: list[dict[str, Any]],
    config: dict,
    cues: list[dict[str, Any]] | None = None,
    album: str = "",
) -> str:
    """WHICK ASS SSOT — 곡 시작 TitleCard + EN 위/KO 아래."""
    from app.services.ass_subtitle_service import build_whick_playlist_ass

    return build_whick_playlist_ass(tracks, cues, config=config, album=album)


def _default_playlist_hashtags() -> str:
    from app.services.brand_service import brand_hashtag_defaults

    return brand_hashtag_defaults()[1] or "#Playlist, #Acoustic, #Instrumental, #StudyMusic"


DEFAULT_PLAYLIST_HASHTAGS = ""  # deprecated — _default_playlist_hashtags() 사용


def format_hashtags_csv(value: str | list | None, fallback: str = "") -> str:
    """유튜브 설명용 태그를 '#a, #b, #c' 형식으로 맞춤."""
    if isinstance(value, list):
        tokens = [str(x).strip() for x in value]
    else:
        raw = (value or "").strip()
        if not raw:
            tokens = []
        elif "," in raw:
            tokens = [p.strip() for p in raw.split(",")]
        else:
            tokens = raw.split()
    cleaned: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        tag = token.strip().lstrip("#").strip()
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(tag)
    if not cleaned:
        return fallback
    return ", ".join(f"#{tag}" for tag in cleaned)


def _brand_copyright_line() -> str:
    from app.services.brand_service import brand_footer_text

    return brand_footer_text() or "© WHICK Official"


def build_description_auto_block(
    tracks: list[dict[str, Any]],
    hashtags: str | list | None = None,
    subtitle_mode: str = "both",
    source_url: str = "",
) -> str:
    """트랙리스트·스펙·태그 — 제목/소개와 분리된 자동 블록."""
    from app.services.brand_service import brand_source_url

    src_url = (source_url or "").strip() or brand_source_url()
    parts = ["🎵 Tracklist"]
    if tracks:
        for t in tracks:
            name = (t.get("title") or "").strip() or "Untitled"
            parts.append(f"{fmt_chapter_ts(_track_start(t))} {name}")
    else:
        parts.append("0:00")
    n = len(tracks)
    runtime = fmt_chapter_ts(playlist_runtime_sec(tracks))
    parts.extend(
        [
            "",
            "◎ Album specs",
            f"Tracks: {n} · Runtime: {runtime}",
            "Audio: Studio remaster (AI-assisted)",
            f"Captions: {captions_label(subtitle_mode)}",
        ]
    )
    if src_url:
        parts.append(f"Source: {src_url}")
    copy_line = _brand_copyright_line()
    if copy_line:
        parts.extend(["", copy_line])
    tag_line = format_hashtags_csv(hashtags, _default_playlist_hashtags())
    if tag_line:
        parts.extend(["", tag_line])
    return "\n".join(parts).strip()


def build_playlist_description(
    title: str,
    tracks: list[dict[str, Any]],
    subtitle: str = "",
    hashtags: str | list | None = None,
    description_en: str = "",
    description_ko: str = "",
    subtitle_mode: str = "both",
    source_url: str = "",
) -> str:
    """영어·한글 소개 + 자동 트랙리스트. 썸네일 제목·부제는 넣지 않음."""
    parts: list[str] = []
    en = description_en or ""
    ko = description_ko or ""
    if en.strip():
        parts.extend([en, ""])
    if ko.strip() and not _same_block(ko, en):
        parts.extend([ko, ""])
    if not parts:
        heading = (title or "").strip()
        if heading:
            parts.extend([_display_title(heading), ""])
    auto = build_description_auto_block(
        tracks,
        hashtags=hashtags,
        subtitle_mode=subtitle_mode,
        source_url=source_url,
    )
    parts.append(auto)
    return "\n".join(parts).strip()[:4900]


def _load_thumb_font(size: int, *, bold: bool = False, serif: bool = False):
    from PIL import ImageFont

    candidates: list[str] = []
    if serif:
        candidates.extend(
            [
                "C:/Windows/Fonts/georgiab.ttf" if bold else "C:/Windows/Fonts/georgia.ttf",
                "C:/Windows/Fonts/timesbd.ttf" if bold else "C:/Windows/Fonts/times.ttf",
                "C:/Windows/Fonts/cambriab.ttf" if bold else "C:/Windows/Fonts/cambria.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
            ]
        )
    if bold:
        candidates.extend(
            [
                "C:/Windows/Fonts/malgunbd.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            ]
        )
    candidates.extend(
        [
            "C:/Windows/Fonts/malgun.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_text_width(draw, text: str, font, max_width: int) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    original = t
    while t:
        bb = draw.textbbox((0, 0), t, font=font)
        if bb[2] - bb[0] <= max_width:
            break
        t = t[:-1]
    if t != original and len(t) > 1:
        t = t[:-1] + "…"
    return t


def _wrap_text(draw, text: str, font, max_width: int, max_lines: int = 2) -> list[str]:
    words = (text or "").strip().split()
    if not words:
        return []
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
            if len(lines) >= max_lines:
                break
    if len(lines) < max_lines:
        lines.append(_fit_text_width(draw, cur, font, max_width))
    elif cur:
        lines[-1] = _fit_text_width(draw, f"{lines[-1]} {cur}", font, max_width)
    return [ln for ln in lines[:max_lines] if ln]


def _fit_single_line_title(draw, text: str, font_size: int, max_width: int, *, min_size: int = 18) -> tuple:
    """한 줄 제목 — 폰트를 줄여 전체 문자열이 들어가게."""
    t = (text or "").strip()
    if not t:
        from PIL import ImageFont
        return ImageFont.load_default(), ""
    size = int(font_size)
    while size >= min_size:
        font = _load_thumb_font(size, bold=True)
        bb = draw.textbbox((0, 0), t, font=font)
        if bb[2] - bb[0] <= max_width:
            return font, t
        size -= 1
    font = _load_thumb_font(min_size, bold=True)
    return font, _fit_text_width(draw, t, font, max_width)


def _is_mostly_latin(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if ord(c) < 128)
    return latin / len(letters) >= 0.7


def _hero_title_parts(title: str, subtitle: str) -> tuple[str, str]:
    """
    Modern Acoustic 썸네일용 표시 제목.
    예: 'Modern Acoustic Classics : Café Healing' + KO부제
      → hero 'Modern Acoustic', sub = KO부제 (또는 영문 나머지)
    """
    main = (title or "Playlist").strip() or "Playlist"
    sub = (subtitle or "").strip()
    leftover = ""
    if ":" in main:
        a, b = main.split(":", 1)
        main, leftover = a.strip(), b.strip()
    words = main.split()
    # 긴 영문 제목은 앞 2단어를 히어로로 (참고 썸네일과 동일)
    if len(words) >= 3 and _is_mostly_latin(main):
        hero = " ".join(words[:2])
        rest = " ".join(words[2:])
        if leftover:
            rest = f"{rest} · {leftover}".strip(" ·")
        if not sub:
            sub = rest or leftover
        return hero, sub
    if leftover and not sub:
        sub = leftover
    return main, sub


def make_playlist_thumbnail(
    bg_path: Path | None,
    out_path: Path,
    title: str,
    track_names: list[str],
    subtitle: str = "",
    *,
    font_tag: int = 24,
    font_title: int = 72,
    font_sub: int = 36,
    font_meta: int = 24,
    layout: str = "album",
    title_single_line: bool = True,
    positions: dict | None = None,
) -> Path:
    """
    Modern Acoustic Classics 썸네일 (1280×720) — https://youtu.be/fMUJmrXBDSc
      블러 배경 + 왼쪽 프레임 사각 커버 + 오른쪽 FULL ALBUM / 제목 / 부제 / 메타.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
    except ImportError:
        if bg_path and bg_path.exists():
            shutil.copy2(bg_path, out_path)
            return out_path
        raise RuntimeError("썸네일 생성에 Pillow가 필요합니다. pip install pillow")

    w, h = 1280, 720
    if bg_path and bg_path.exists():
        cover = Image.open(bg_path).convert("RGB")
    else:
        cover = Image.new("RGB", (w, h), (28, 30, 36))

    # 1) 어둡게 블러된 풀블리드 배경 (+ 약한 비네트)
    cw, ch = cover.size
    scale = max(w / cw, h / ch) * 1.2
    bg = cover.resize((int(cw * scale), int(ch * scale)), Image.LANCZOS)
    left = (bg.width - w) // 2
    top = (bg.height - h) // 2
    bg = bg.crop((left, top, left + w, top + h)).filter(ImageFilter.GaussianBlur(32))
    bg = ImageEnhance.Brightness(bg).enhance(0.42).convert("RGBA")
    vignette = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    for i in range(90):
        a = int(90 * (i / 90) ** 1.4)
        vd.rectangle([i, i, w - 1 - i, h - 1 - i], outline=(0, 0, 0, a))
    canvas = Image.alpha_composite(bg, vignette)

    # 2) 왼쪽 정사각 커버 — 다크 매트 + 얇은 블랙 보더 (화이트 프레임 아님)
    art_size = 480
    side = min(cover.width, cover.height)
    ox = (cover.width - side) // 2
    oy = (cover.height - side) // 2
    art = cover.crop((ox, oy, ox + side, oy + side)).resize((art_size, art_size), Image.LANCZOS)

    mat_pad = 22
    border = 3
    outer = art_size + mat_pad * 2
    matte = Image.new("RGBA", (outer, outer), (38, 40, 46, 230))
    inner = Image.new("RGBA", (art_size + border * 2, art_size + border * 2), (8, 8, 10, 255))
    inner.paste(art.convert("RGBA"), (border, border))
    matte.paste(inner, (mat_pad - border, mat_pad - border), inner)

    art_x = 72
    art_y = (h - outer) // 2
    shadow = Image.new("RGBA", (outer + 48, outer + 48), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [10, 14, outer + 30, outer + 34],
        radius=8,
        fill=(0, 0, 0, 180),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas.paste(shadow, (art_x - 14, art_y - 8), shadow)
    canvas.paste(matte, (art_x, art_y), matte)

    # 3) 오른쪽 텍스트
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    f_tag = _load_thumb_font(max(12, int(font_tag)), bold=True)
    f_title = _load_thumb_font(max(20, int(font_title)), bold=True)
    f_sub = _load_thumb_font(max(14, int(font_sub)), bold=True)
    f_meta = _load_thumb_font(max(12, int(font_meta)), bold=False)
    title_shrink = max(20, int(font_title * 0.78))

    text_left = art_x + outer + 48
    text_max = w - text_left - 48
    gold = (232, 200, 150, 255)

    if layout == "custom":
        main_title = (title or "").strip() or "Title"
        sub = (subtitle or "").strip()
    else:
        main_title, sub = _hero_title_parts(title, subtitle)

    def shadow_text(xy, text, font, fill, off=3):
        x, y = xy
        draw.text((x + off, y + off), text, font=font, fill=(0, 0, 0, 180))
        draw.text((x, y), text, font=font, fill=fill)

    pos = positions or {}
    default_y = 168

    def _xy(key: str, dx: int, dy: int) -> tuple[int, int]:
        p = pos.get(key) or {}
        return int(p.get("x", dx)), int(p.get("y", dy))

    tag_xy = _xy("tag", text_left, default_y)
    title_xy = _xy("title", text_left, default_y + 48)
    sub_xy = _xy("sub", text_left, default_y + 48 + int(font_title) + 12)
    meta_xy = _xy("meta", text_left, min(default_y + 48 + int(font_title) + 70, h - 64))

    shadow_text(tag_xy, "FULL ALBUM", f_tag, gold, off=2)

    if title_single_line or layout == "custom":
        f_title, title_line = _fit_single_line_title(draw, main_title, font_title, text_max)
        if title_line:
            shadow_text(title_xy, title_line, f_title, (255, 255, 255, 255), off=4)
    else:
        ty = title_xy[1]
        words = main_title.split()
        if len(words) == 2 and _is_mostly_latin(main_title):
            title_lines = words
        else:
            title_lines = _wrap_text(draw, main_title, f_title, text_max, max_lines=2)
            if len(title_lines) == 1:
                bb = draw.textbbox((0, 0), title_lines[0], font=f_title)
                if bb[2] - bb[0] > text_max:
                    f_title = _load_thumb_font(title_shrink, bold=True)
                    title_lines = _wrap_text(draw, main_title, f_title, text_max, max_lines=2)
        for line in title_lines:
            shadow_text((text_left, ty), line, f_title, (255, 255, 255, 255), off=4)
            bb = draw.textbbox((0, 0), line, font=f_title)
            ty += (bb[3] - bb[1]) + 4

    if sub:
        sub_line = _fit_text_width(draw, sub, f_sub, text_max)
        shadow_text(sub_xy, sub_line, f_sub, (255, 255, 255, 245), off=2)

    n = len(track_names)
    meta = f"Instrumental • {n}곡" if n else "Instrumental Playlist"
    meta = _fit_text_width(draw, meta, f_meta, text_max)
    shadow_text(meta_xy, meta, f_meta, (210, 210, 218, 255), off=2)

    composed = Image.alpha_composite(canvas, overlay).convert("RGB")
    composed.save(out_path, "JPEG", quality=94)
    return out_path


def build_playlist_video(
    audio_path: Path,
    track_visuals: list[tuple[Path, float]],
    ass_path: Path,
    output_path: Path,
    duration_sec: float,
    config: dict,
) -> Path:
    """곡마다 커버 전환 + EQ + 자막을 한 번에 인코딩. thumbnail.jpg는 넣지 않음."""
    if not find_ffmpeg():
        raise RuntimeError("FFmpeg가 설치되어 있지 않습니다.")
    if not track_visuals:
        raise ValueError("곡별 커버 이미지가 없습니다")

    video_cfg = config.get("video", {})
    overlay_cfg = config.get("overlay", {})
    w = video_cfg.get("width", 1920)
    h = video_cfg.get("height", 1080)
    encoder = detect_video_encoder(video_cfg.get("encoder", "auto"))
    fade = float(video_cfg.get("fade_in_sec", 0.4))
    audio_bitrate = str(config.get("audio", {}).get("output_bitrate", "320k"))
    audio_args = _audio_mux_args(audio_path, preview_fast=False, bitrate=audio_bitrate)
    eq_style = str(overlay_cfg.get("eq_bar_style", "none"))
    eq_enabled = eq_style not in ("none", "off", "") and bool(overlay_cfg.get("eq_bar_enabled", True))
    eq_w = int(overlay_cfg.get("eq_bar_w", 1000))
    eq_h = int(overlay_cfg.get("eq_bar_h", 80))
    eq_color = str(overlay_cfg.get("eq_bar_color", "#FFFFFF"))
    eq_align = str(overlay_cfg.get("eq_bar_align") or "bottom_center")
    if eq_align == "bottom_center":
        eq_x = max(0, (w - eq_w) // 2)
        eq_y = max(0, h - eq_h - 24)
    else:
        eq_x = int(overlay_cfg.get("eq_bar_x", (w - eq_w) // 2))
        eq_y = int(overlay_cfg.get("eq_bar_y", max(0, h - eq_h - 24)))
        eq_x = max(0, min(eq_x, max(0, w - eq_w)))
        eq_y = max(0, min(eq_y, max(0, h - eq_h)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fps = int(video_cfg.get("fps", 30))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ass_local = tmp_path / "subtitles.ass"
        ass_local.write_text(ass_path.read_text(encoding="utf-8"), encoding="utf-8")
        sub_vf = build_subtitles_vf(ass_local, fade_in=fade)

        still_inputs: list[str] = []
        n = len(track_visuals)
        for i, (img, dur) in enumerate(track_visuals):
            frame = tmp_path / f"bg_{i:03d}.jpg"
            make_cover_frame(img, frame, bg_w=w, bg_h=h)
            t = max(0.2, float(dur))
            still_inputs.extend(
                ["-loop", "1", "-framerate", str(fps), "-t", str(t), "-i", str(frame)]
            )

        prep = ";".join(f"[{i}:v]format=yuv420p,setsar=1[v{i}]" for i in range(n))
        concat_pads = "".join(f"[v{i}]" for i in range(n))
        fc_bg = f"{prep};{concat_pads}concat=n={n}:v=1:a=0[bg]"

        eq_path = tmp_path / "eq_bars.mov"
        has_eq = False
        if eq_enabled:
            from app.services.eq_bar_service import make_eq_video

            has_eq = make_eq_video(
                audio_path,
                eq_path,
                width=eq_w,
                height=eq_h,
                style=eq_style,
                color=eq_color,
            )

        wm = prepare_watermark_png(tmp_path / "watermark.png", video_h=h)
        wx, wy = watermark_xy(w, h)

        if has_eq:
            eq_idx = n
            next_i = n + 1
            wm_in = None
            extra: list[str] = ["-i", str(eq_path)]
            if wm:
                wm_in = f"[{next_i}:v]"
                extra += ["-i", str(wm)]
                next_i += 1
            aud_idx = next_i
            extra += ["-i", str(audio_path)]
            fc = (
                fc_bg
                + ";"
                + _eq_overlay_fc(
                    eq_w,
                    eq_h,
                    align=eq_align,
                    eq_x=eq_x,
                    eq_y=eq_y,
                    bottom_pad=24,
                    main="[bg]",
                    eq_in=f"[{eq_idx}:v]",
                    yuv=False,
                )
                + f";[outv]{sub_vf}[vsub]"
            )
            if wm_in:
                fc += ";" + watermark_overlay_fc("[vsub]", wm_in, "vout", x=wx, y=wy)
            else:
                fc += ";[vsub]format=yuv420p[vout]"
            _run([
                "ffmpeg", "-y",
                *still_inputs,
                *extra,
                "-filter_complex", fc,
                "-map", "[vout]", "-map", f"{aud_idx}:a",
                *_video_encode_args(encoder, config),
                *audio_args,
                "-t", str(duration_sec),
                "-movflags", "+faststart",
                str(output_path),
            ])
        else:
            extra = []
            next_i = n
            wm_in = None
            if wm:
                wm_in = f"[{next_i}:v]"
                extra += ["-i", str(wm)]
                next_i += 1
            aud_idx = next_i
            extra += ["-i", str(audio_path)]
            fc = f"{fc_bg};[bg]{sub_vf}[vsub]"
            if wm_in:
                fc += ";" + watermark_overlay_fc("[vsub]", wm_in, "vout", x=wx, y=wy)
            else:
                fc += ";[vsub]format=yuv420p[vout]"
            _run([
                "ffmpeg", "-y",
                *still_inputs,
                *extra,
                "-filter_complex", fc,
                "-map", "[vout]", "-map", f"{aud_idx}:a",
                *_video_encode_args(encoder, config),
                *audio_args,
                "-shortest",
                "-t", str(duration_sec),
                "-movflags", "+faststart",
                str(output_path),
            ])

    return output_path


def run_playlist_pipeline(
    project_dirs: list[Path],
    output_dir: Path,
    *,
    title: str | None = None,
    subtitle: str = "",
    config: dict | None = None,
) -> dict[str, Any]:
    """여러 프로젝트 폴더 → 합본 mp4 + 썸네일 + 설명(챕터)."""
    if len(project_dirs) < 2:
        raise ValueError("합본 영상은 프로젝트를 2개 이상 선택하세요.")

    cfg = config or get_default_config()
    from app.services.editor_service import merge_editor_into_pipeline

    cfg = merge_editor_into_pipeline(project_dirs[0], cfg)

    # 사전 점검: 음원·커버·가사 누락 시 인코딩 전에 중단.
    # 자막 모드가 요구하는 언어 가사(both→en+ko, en→en, ko→ko)도 함께 검사.
    from app.services.preflight_service import preflight_playlist_tracks

    preflight_playlist_tracks(
        project_dirs, (cfg.get("subtitle") or {}).get("mode")
    )

    video = cfg.setdefault("video", {})
    video["crf"] = min(int(video.get("crf", 17) or 17), 17)
    video["preset"] = "slow"
    video["amf_quality"] = "quality"
    video["nvenc_preset"] = "p7"
    audio = cfg.setdefault("audio", {})
    audio["output_bitrate"] = "320k"
    if not find_ffmpeg():
        raise RuntimeError("FFmpeg가 필요합니다.")

    output_dir.mkdir(parents=True, exist_ok=True)
    tracks: list[dict[str, Any]] = []
    remastered_files: list[Path] = []
    cover_images: list[Path] = []
    cur = 0.0
    album_fallback = pick_album_fallback_cover(project_dirs)
    last_cover: Path | None = None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for i, project_dir in enumerate(project_dirs):
            assets = find_project_assets(project_dir)
            if not assets.get("audio_paths"):
                raise ValueError(f"음원 없음: {project_dir.name}")
            audio_in = Path(assets["audio_paths"][0])
            track_title = assets.get("track_title") or project_dir.name
            remastered = tmp_path / f"track_{i:02d}.m4a"
            remaster_audio(audio_in, remastered, cfg)
            dur = probe_duration(remastered)
            remastered_files.append(remastered)
            own_thumb = project_dir / "thumbnail.jpg"
            cover = (
                pick_track_playlist_cover(assets)
                or album_fallback
                or last_cover
                or (own_thumb if own_thumb.is_file() else None)
            )
            if not cover:
                raise ValueError(
                    f"커버가 없고 앨범 썸네일도 없습니다: {project_dir.name}"
                )
            last_cover = cover
            cover_images.append(cover)
            tracks.append(
                {
                    "start": cur,
                    "end": cur + dur,
                    "duration": dur,
                    "num": i + 1,
                    "title": track_title,
                    "lyrics_en": assets.get("lyrics_en") or "",
                    "lyrics_ko": assets.get("lyrics_ko") or "",
                    "project": str(project_dir),
                    "audio_path": str(remastered),
                    "source_audio": str(audio_in),
                }
            )
            cur += dur

        total_dur = cur
        concat_list = tmp_path / "concat.txt"
        # Windows ffmpeg concat: forward slashes
        concat_list.write_text(
            "\n".join(f"file '{p.resolve().as_posix()}'" for p in remastered_files),
            encoding="utf-8",
        )
        concat_audio = output_dir / "playlist_audio.m4a"
        _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-vn", "-c", "copy",
            str(concat_audio),
        ])

        playlist_title = title or f"Playlist ({len(tracks)} tracks)"

        # Whisper listen-align — 실제 가창 구간에 가사 하드싱크
        from app.services.lyric_timing_service import build_album_cues, get_whisper_model
        from app.services.preflight_service import validate_aligned_cues

        whisper = get_whisper_model()
        cues = build_album_cues(tracks, whisper_model=whisper)

        # 사후 검증: 자막 큐 개수·커버리지·역전·겹침·경계 초과 — 문제 시 인코딩 전 중단
        validate_aligned_cues(cues, tracks)

        (output_dir / "lyrics_timing.json").write_text(
            json.dumps(cues, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        ass_content = build_playlist_ass(tracks, cfg, cues=cues, album=playlist_title)
        ass_path = output_dir / "subtitles.ass"
        ass_path.write_text(ass_content, encoding="utf-8")

        if not cover_images or len(cover_images) != len(tracks):
            raise ValueError("합본 영상에 쓸 곡별 커버 이미지가 없습니다. thumbnail.jpg는 유튜브 목록용입니다.")

        thumb_path = output_dir / "thumbnail.jpg"
        saved_thumb = project_dirs[0] / "thumbnail.jpg"
        if saved_thumb.is_file():
            shutil.copyfile(saved_thumb, thumb_path)
        else:
            make_playlist_thumbnail(
                cover_images[0],
                thumb_path,
                playlist_title,
                [t["title"] for t in tracks],
                subtitle=subtitle or "",
            )

        video_name = re.sub(r'[<>:"/\\|?*]', "_", playlist_title)[:80]
        video_out = output_dir / f"{video_name}.mp4"
        visuals = [(cover_images[i], float(tracks[i]["duration"])) for i in range(len(tracks))]
        build_playlist_video(
            concat_audio, visuals, ass_path, video_out, total_dur, cfg
        )

        editor = cfg.get("_editor") or {}
        editor_yt = editor.get("youtube") or {}
        sub_mode = (editor.get("subtitle") or {}).get("mode") or (cfg.get("subtitle") or {}).get("mode") or "both"
        # 설명은 위젯 구성(desc_blocks) SSOT으로 생성 — 6단계 미리보기와 동일한 결과 보장
        from app.services.desc_blocks_service import build_description_from_blocks

        _blk_ctx = {
            "album_title": playlist_title,
            "description_en": editor_yt.get("description_en") or "",
            "description_ko": editor_yt.get("description_ko") or "",
            "tracks": tracks,
            "subtitle_mode": str(sub_mode),
            "hashtags": editor_yt.get("hashtags") or editor_yt.get("tags"),
            "include_lyrics_in_description": bool(editor_yt.get("include_lyrics_in_description")),
            "lyrics_ko": "",
            "lyrics_en": "",
            "runtime": total_dur,
        }
        description = build_description_from_blocks(_blk_ctx)
        if not description:
            description = build_playlist_description(
                playlist_title,
                tracks,
                hashtags=editor_yt.get("hashtags") or editor_yt.get("tags"),
                description_en=editor_yt.get("description_en") or "",
                description_ko=editor_yt.get("description_ko") or "",
                subtitle_mode=str(sub_mode),
            )
        (output_dir / "youtube_description.txt").write_text(description, encoding="utf-8")
        (output_dir / "title.txt").write_text(playlist_title, encoding="utf-8")

        # 업로드용: find_project_assets가 thumbnail.* / title 인식
        if thumb_path.exists() and not (output_dir / f"thumbnail{thumb_path.suffix}").exists():
            pass  # already thumbnail.jpg

        meta = {
            "title": playlist_title,
            "subtitle": subtitle,
            "track_count": len(tracks),
            "tracks": [
                {
                    "title": t["title"],
                    "start": t["start"],
                    "end": t["end"],
                    "chapter": fmt_chapter_ts(t["start"]),
                    "project": t["project"],
                }
                for t in tracks
            ],
            "duration_sec": total_dur,
            "lyric_cues": len(cues),
            "whisper_align": whisper is not None,
            "video_output": str(video_out),
            "thumbnail": str(thumb_path),
            "ass_path": str(ass_path),
            "description": description,
            "encoder": detect_video_encoder(cfg.get("video", {}).get("encoder", "auto")),
            "created_at": datetime.now().isoformat(),
        }
        (output_dir / "pipeline_result.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        remember_pipeline_output(
            project_dirs[0],
            video_out,
            {"output_dir": str(output_dir), "track_count": len(tracks)},
        )
        return meta
