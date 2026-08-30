"""유튜브 스튜디오 편집기 — editor_config, 미리보기, 설명 초안."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.services.pipeline_defaults import get_default_config
from app.services.playlist_pipeline_service import (
    _same_block,
    build_description_auto_block,
    build_playlist_description,
    format_hashtags_csv,
)
from app.services.thumbnail_canvas_service import (
    default_canvas_config,
    migrate_thumbnail_to_canvas,
    render_thumbnail_canvas,
)
from app.services.workflow_service import find_project_assets
from app.config import settings

EDITOR_CONFIG_FILE = "editor_config.json"
YOUTUBE_DESC_FILE = "youtube_description.txt"
PREVIEW_VIDEO_NAME = "preview_short.mp4"
PREVIEW_DURATION_SEC = 30.0
PREVIEW_VIDEO_NAMES = {PREVIEW_VIDEO_NAME.lower(), "preview_30s.mp4"}
_TRACK_NUM_RE = re.compile(r"^\d+\s+")

DEFAULT_EDITOR_CONFIG: dict[str, Any] = {
    "version": 1,
    "mode": "single",
    "project_paths": [],
    "last_step": 1,
    "thumbnail": {
        "layout": "canvas",
        "title": "",
        "subtitle": "",
        "background": {"image": "", "mode": "modern", "dim": 0.25},
        "boxes": [],
    },
    "subtitle": {
        "mode": "both",
        "margin_v_en": 182,
        "margin_v_ko": 100,
        "font_size_en": 68,
        "font_size_ko": 68,
        "title_intro_sec": 6.0,
        "track_header_enabled": True,
        "track_header_y": 70,
        "font_size_title": 42,
        "title_color": "#FFFFFF",
    },
    "overlay": {
        "eq_bar_enabled": False,
        "eq_bar_style": "none",
        "eq_bar_x": 460,
        "eq_bar_y": 980,
        "eq_bar_w": 1000,
        "eq_bar_h": 80,
        "eq_bar_color": "#FFFFFF",
        "eq_bar_align": "bottom_center",
    },
    "remaster": {
        "low_db": 1.8,
        "high_db": 0.3,
        "stereo_width": 1.12,
        "strip_fingerprint": True,
    },
    "youtube": {
        "title": "",
        "subtitle": "",
        "description_ko": "",
        "description_en": "",
        "include_lyrics_in_description": False,
        "tags": [
            "WHICK",
            "WHICK Official",
            "playlist",
            "full album",
            "full playlist",
            "acoustic",
            "instrumental",
            "relaxing music",
            "study music",
            "cafe music",
            "chill music",
            "original music",
            "플레이리스트",
            "어쿠스틱",
            "인스트루멘탈",
            "공부음악",
            "카페음악",
            "힐링음악",
        ],
        "hashtags": "#WHICK, #Playlist, #Acoustic, #Instrumental, #StudyMusic",
        "tracks": [],
        "description_locked": False,
    },
}


def editor_config_path(project_dir: Path) -> Path:
    return project_dir / EDITOR_CONFIG_FILE


def _deep_merge(base: dict, updates: dict) -> dict:
    out = deepcopy(base)
    for key, val in updates.items():
        if isinstance(val, list):
            out[key] = deepcopy(val)
        elif isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def user_style_path() -> Path:
    """이 PC 사용자 스타일. 배포 기본값이 아님."""
    d = settings.data_dir
    d.mkdir(parents=True, exist_ok=True)
    return d / "editor_user_style.json"


def extract_user_style(cfg: dict) -> dict:
    """앨범 고유 내용(제목·가사·커버·설명)을 뺀 작업 스타일."""
    thumb = cfg.get("thumbnail") or {}
    bg = {k: v for k, v in dict(thumb.get("background") or {}).items() if k != "image"}
    boxes = []
    for b in thumb.get("boxes") or []:
        if isinstance(b, dict):
            boxes.append({k: v for k, v in b.items() if k != "text"})
    return {
        "subtitle": deepcopy(cfg.get("subtitle") or {}),
        "overlay": deepcopy(cfg.get("overlay") or {}),
        "remaster": deepcopy(cfg.get("remaster") or {}),
        "thumbnail": {
            "layout": thumb.get("layout") or "canvas",
            "template_id": thumb.get("template_id"),
            "background": bg,
            "boxes": boxes,
        },
    }


def load_user_style() -> dict:
    path = user_style_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_user_style(cfg: dict) -> None:
    path = user_style_path()
    path.write_text(
        json.dumps(extract_user_style(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def apply_user_style(cfg: dict, style: dict) -> dict:
    if not style:
        return cfg
    out = deepcopy(cfg)
    for key in ("subtitle", "overlay", "remaster"):
        if isinstance(style.get(key), dict) and style[key]:
            out[key] = _deep_merge(out.get(key) or {}, style[key])
    st = style.get("thumbnail") or {}
    if not isinstance(st, dict) or not st:
        return out
    thumb = out.setdefault("thumbnail", {})
    if st.get("template_id"):
        thumb["template_id"] = st["template_id"]
    if st.get("layout"):
        thumb["layout"] = st["layout"]
    if isinstance(st.get("background"), dict):
        img = (thumb.get("background") or {}).get("image")
        thumb["background"] = {**(thumb.get("background") or {}), **st["background"]}
        if img:
            thumb["background"]["image"] = img
    saved_boxes = st.get("boxes")
    if isinstance(saved_boxes, list) and saved_boxes:
        texts = {
            b.get("id"): b.get("text")
            for b in (thumb.get("boxes") or [])
            if isinstance(b, dict)
        }
        new_boxes = []
        for sb in saved_boxes:
            if not isinstance(sb, dict):
                continue
            nb = deepcopy(sb)
            tid = nb.get("id")
            if tid in texts and texts[tid]:
                nb["text"] = texts[tid]
            elif not nb.get("text"):
                nb["text"] = ""
            new_boxes.append(nb)
        if new_boxes:
            thumb["boxes"] = new_boxes
    return out


def _cover_image_name(assets: dict) -> str:
    covers = assets.get("cover_image_paths") or []
    if covers:
        return str(covers[0])
    images = assets.get("image_paths") or []
    for p in images:
        if Path(p).name.lower() != "thumbnail.jpg":
            return str(p)
    return str(images[0]) if images else ""


def _ensure_thumbnail_canvas(cfg: dict, project_dir: Path, assets: dict) -> dict:
    thumb = cfg.setdefault("thumbnail", {})
    bg = thumb.setdefault("background", {})
    # 생성본 thumbnail.jpg를 배경으로 쓰는 설정은 원본 커버로 교체
    image_name = str(bg.get("image") or "")
    if not image_name or Path(image_name).name.lower() == "thumbnail.jpg":
        better = _cover_image_name(assets)
        if better:
            bg["image"] = better

    boxes = thumb.get("boxes")
    if thumb.get("layout") == "canvas" and isinstance(boxes, list) and len(boxes) > 0:
        return cfg
    image_name = _cover_image_name(assets)
    title = thumb.get("title") or assets.get("track_title") or project_dir.name
    subtitle = thumb.get("subtitle") or ""
    if thumb.get("positions") or thumb.get("font_title"):
        migrated = migrate_thumbnail_to_canvas(thumb, assets, project_dir)
    else:
        migrated = default_canvas_config(title, subtitle, image_name)
    cfg["thumbnail"] = {**thumb, **migrated, "title": title, "subtitle": subtitle}
    return cfg


def default_editor_config(project_dir: Path, assets: dict | None = None) -> dict:
    assets = assets or find_project_assets(project_dir)
    title = (assets.get("track_title") or project_dir.name).strip()
    subtitle = ""
    image_name = _cover_image_name(assets)
    cfg = deepcopy(DEFAULT_EDITOR_CONFIG)
    cfg["thumbnail"] = default_canvas_config(title, subtitle, image_name)
    cfg["thumbnail"]["title"] = title
    cfg["youtube"]["title"] = title
    return cfg


def load_editor_config(project_dir: Path) -> dict:
    path = editor_config_path(project_dir)
    assets = find_project_assets(project_dir)
    base = apply_user_style(default_editor_config(project_dir, assets), load_user_style())
    if not path.exists():
        return _ensure_thumbnail_canvas(base, project_dir, assets)
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _ensure_thumbnail_canvas(base, project_dir, assets)
    merged = _deep_merge(base, stored)
    return _ensure_thumbnail_canvas(merged, project_dir, assets)


def save_editor_config(project_dir: Path, updates: dict) -> dict:
    current = load_editor_config(project_dir)
    incoming_thumb = updates.get("thumbnail")
    incoming_boxes = None
    if isinstance(incoming_thumb, dict) and isinstance(incoming_thumb.get("boxes"), list):
        incoming_boxes = deepcopy(incoming_thumb["boxes"])
    merged = _deep_merge(current, updates)
    if incoming_boxes is not None:
        merged.setdefault("thumbnail", {})["boxes"] = incoming_boxes
        merged["thumbnail"]["layout"] = "canvas"
    assets = find_project_assets(project_dir)
    merged = _ensure_thumbnail_canvas(merged, project_dir, assets)
    editor_config_path(project_dir).write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    save_user_style(merged)
    return merged


def build_remaster_chain(remaster: dict | None) -> str:
    """WHICK studio DSP — 슬라이더 값으로 FFmpeg -af 체인 생성."""
    r = remaster or {}
    low = float(r.get("low_db", 1.8))
    high = float(r.get("high_db", 0.3))
    stereo = float(r.get("stereo_width", 1.12))
    return (
        f"lowshelf=g={low:.1f}:f=90,"
        f"equalizer=f=14000:t=q:w=1.2:g={max(0.0, high + 0.9):.1f},"
        f"highshelf=g={high:.1f}:f=9000,"
        f"extrastereo=m={stereo:.2f}:c=0,"
        "aeval='0.96*val(ch)+0.04*tanh(1.2*val(ch))':c=same,"
        "loudnorm=I=-14:LRA=11:TP=-1.0"
    )


def merge_editor_into_pipeline(project_dir: Path, global_config: dict) -> dict:
    """곡별 editor_config → pipeline config 병합."""
    editor = load_editor_config(project_dir)
    cfg = deepcopy(global_config)

    sub = cfg.setdefault("subtitle", {})
    for key in (
        "mode",
        "margin_v_lyrics_en",
        "margin_v_lyrics_ko",
        "title_intro_sec",
        "font_lyrics_en",
        "font_lyrics_ko",
        "font_title",
        "margin_v_title",
        "track_header_enabled",
        "title_color",
    ):
        src = {
            "mode": "mode",
            "margin_v_lyrics_en": "margin_v_en",
            "margin_v_lyrics_ko": "margin_v_ko",
            "title_intro_sec": "title_intro_sec",
            "font_lyrics_en": "font_size_en",
            "font_lyrics_ko": "font_size_ko",
            "font_title": "font_size_title",
            "margin_v_title": "track_header_y",
            "track_header_enabled": "track_header_enabled",
            "title_color": "title_color",
        }[key]
        if src in editor.get("subtitle", {}):
            if key == "mode":
                sub["mode"] = editor["subtitle"][src]
            else:
                sub[key] = editor["subtitle"][src]

    remaster = editor.get("remaster") or {}
    cfg.setdefault("audio", {})["master_chain"] = build_remaster_chain(remaster)
    cfg.setdefault("audio", {})["strip_fingerprint"] = bool(remaster.get("strip_fingerprint", True))

    ov = editor.get("overlay") or {}
    overlay = cfg.setdefault("overlay", {})
    for key in (
        "eq_bar_style",
        "eq_bar_x",
        "eq_bar_y",
        "eq_bar_w",
        "eq_bar_h",
        "eq_bar_color",
        "eq_bar_align",
    ):
        if key in ov:
            overlay[key] = ov[key]
    style = str(overlay.get("eq_bar_style", ov.get("eq_bar_style", "none")))
    overlay["eq_bar_enabled"] = style not in ("none", "off", "") and bool(
        ov.get("eq_bar_enabled", overlay.get("eq_bar_enabled", True))
    )
    overlay["eq_bar_color"] = str(overlay.get("eq_bar_color") or ov.get("eq_bar_color") or "#FFFFFF")
    overlay["eq_bar_align"] = str(overlay.get("eq_bar_align") or ov.get("eq_bar_align") or "bottom_center")

    cfg["_editor"] = editor
    return cfg


def _run_ffmpeg(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "")[-2000:]
        raise RuntimeError(f"FFmpeg 실패: {err}")


def preview_remaster_audio(
    audio_path: Path,
    out_path: Path,
    remaster: dict,
    *,
    duration_sec: float = 30.0,
) -> Path:
    chain = build_remaster_chain(remaster)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(audio_path),
        "-t", str(duration_sec),
        "-map_metadata", "-1",
        "-af", chain,
        "-c:a", "aac", "-b:a", "320k",
        str(out_path),
    ]
    _run_ffmpeg(cmd)
    return out_path


def resolve_youtube_tags(raw) -> list[str]:
    tags = [str(t).strip() for t in (raw or []) if str(t).strip()]
    stale = {
        ("Music", "Acoustic", "Instrumental"),
        ("Suno", "AI Music", "Music", "Playlist"),
    }
    if not tags or tuple(tags) in stale:
        return list(DEFAULT_EDITOR_CONFIG["youtube"]["tags"])
    return tags[:30]


def resolve_youtube_hashtags(raw, tags=None) -> str:
    stale = {
        "#Music #Acoustic #Instrumental",
        "#Music, #Acoustic, #Instrumental",
        "#Playlist #Music #Suno #AIMusic #WHICK",
        "#Playlist, #Music, #Suno, #AIMusic, #WHICK",
    }
    text = (raw or "").strip() if isinstance(raw, str) else ""
    if not text or text in stale:
        return DEFAULT_EDITOR_CONFIG["youtube"]["hashtags"]
    return format_hashtags_csv(raw or tags, DEFAULT_EDITOR_CONFIG["youtube"]["hashtags"])


def _subtitle_mode(editor: dict | None, youtube: dict | None = None) -> str:
    if editor:
        mode = (editor.get("subtitle") or {}).get("mode")
        if mode:
            return str(mode)
    return "both"


def build_single_description(project_dir: Path, youtube: dict, assets: dict, editor: dict | None = None) -> str:
    title = (youtube.get("title") or assets.get("track_title") or project_dir.name).strip()
    ko = youtube.get("description_ko") or ""
    en = youtube.get("description_en") or ""
    from app.services.pipeline_service import probe_duration

    audio = (assets.get("audio_paths") or [None])[0]
    runtime = probe_duration(Path(audio)) if audio else 0.0
    intro_parts: list[str] = []
    if en.strip():
        intro_parts.append(en)
    if ko.strip() and not _same_block(ko, en):
        intro_parts.append(ko)
    parts: list[str] = []
    for block in intro_parts:
        parts.extend([block, ""])
    auto = build_description_auto_block(
        [{"start": 0, "duration": runtime, "title": assets.get("track_title") or title}],
        hashtags=youtube.get("hashtags") or youtube.get("tags"),
        subtitle_mode=_subtitle_mode(editor),
    )
    parts.append(auto)
    if youtube.get("include_lyrics_in_description"):
        if assets.get("lyrics_ko"):
            parts.extend(["", "[가사]", assets["lyrics_ko"][:2500]])
        elif assets.get("lyrics_en"):
            parts.extend(["", "[Lyrics]", assets["lyrics_en"][:2500]])
    return "\n".join(parts).strip()[:4900]


def _tracks_need_chapters(tracks: list, path_count: int) -> bool:
    if path_count >= 2 and len(tracks) != path_count:
        return True
    if len(tracks) < 2:
        return False
    starts = [float(t.get("start_sec") or t.get("start") or 0) for t in tracks]
    return max(starts) <= 0


def ensure_playlist_tracks(project_dir: Path, editor: dict | None = None) -> list[dict]:
    editor = editor or load_editor_config(project_dir)
    paths = [str(p) for p in (editor.get("project_paths") or []) if p]
    yt_tracks = list((editor.get("youtube") or {}).get("tracks") or [])
    if paths and _tracks_need_chapters(yt_tracks, len(paths)):
        return regenerate_playlist_chapters(project_dir, paths)
    return yt_tracks


def _desc_tracks(tracks: list[dict]) -> list[dict]:
    return [
        {
            "start": float(t.get("start_sec") or t.get("start") or 0),
            "duration": float(t.get("duration_sec") or t.get("duration") or 0),
            "title": t.get("title") or "",
        }
        for t in tracks
    ]


def _playlist_description_text(title: str, subtitle: str, youtube: dict, editor: dict, tracks: list[dict]) -> str:
    return build_playlist_description(
        title,
        _desc_tracks(tracks),
        hashtags=youtube.get("hashtags"),
        description_en=youtube.get("description_en") or "",
        description_ko=youtube.get("description_ko") or "",
        subtitle_mode=_subtitle_mode(editor),
    )


def _auto_block_text(youtube: dict, editor: dict, tracks: list[dict], *, single_title: str = "", runtime: float = 0.0) -> str:
    if tracks:
        packed = _desc_tracks(tracks)
    else:
        packed = [{"start": 0, "duration": runtime, "title": single_title}]
    return build_description_auto_block(
        packed,
        hashtags=youtube.get("hashtags") or youtube.get("tags"),
        subtitle_mode=_subtitle_mode(editor),
    )


def _load_saved_description(project_dir: Path) -> str | None:
    desc_file = project_dir / YOUTUBE_DESC_FILE
    if not desc_file.is_file():
        return None
    text = desc_file.read_text(encoding="utf-8", errors="ignore")
    if not text.strip():
        return None
    return text


def build_youtube_draft(project_dir: Path) -> dict[str, Any]:
    editor = load_editor_config(project_dir)
    assets = find_project_assets(project_dir)
    yt = editor.get("youtube") or {}
    mode = editor.get("mode") or "single"
    if len(editor.get("project_paths") or []) >= 2:
        mode = "playlist"
        editor["mode"] = mode

    title = yt.get("title") or assets.get("track_title") or project_dir.name
    tracks = list(yt.get("tracks") or [])
    if mode == "playlist":
        tracks = ensure_playlist_tracks(project_dir, editor)
        editor = load_editor_config(project_dir)
        yt = editor.get("youtube") or yt

    saved = _load_saved_description(project_dir)
    locked = bool(yt.get("description_locked")) or bool(saved)

    draft: dict[str, Any] = {
        "mode": mode,
        "title": title,
        "subtitle": yt.get("subtitle") or "",
        "description_ko": yt.get("description_ko") or "",
        "description_en": yt.get("description_en") or "",
        "include_lyrics_in_description": bool(yt.get("include_lyrics_in_description")),
        "tags": resolve_youtube_tags(yt.get("tags")),
        "hashtags": resolve_youtube_hashtags(yt.get("hashtags"), yt.get("tags")),
        "tracks": tracks,
        "description_locked": locked,
        "description_preview": "",
        "auto_block": "",
        "char_count": 0,
    }
    yt_merged = {**yt, **draft}

    from app.services.pipeline_service import probe_duration

    audio = (assets.get("audio_paths") or [None])[0]
    runtime = probe_duration(Path(audio)) if audio else 0.0
    draft["auto_block"] = _auto_block_text(
        yt_merged, editor, tracks, single_title=assets.get("track_title") or title, runtime=runtime
    )

    if saved:
        draft["description_preview"] = saved
        draft["description_locked"] = True
        draft["char_count"] = len(saved)
        return draft

    if mode == "playlist" and draft["tracks"]:
        draft["description_preview"] = _playlist_description_text(
            draft["title"], draft["subtitle"], yt_merged, editor, draft["tracks"]
        )
    else:
        draft["description_preview"] = build_single_description(
            project_dir, {**yt_merged, "title": title}, assets, editor
        )

    draft["char_count"] = len(draft["description_preview"])
    return draft


def save_youtube_draft(project_dir: Path, payload: dict) -> dict[str, Any]:
    editor = load_editor_config(project_dir)
    yt = editor.setdefault("youtube", {})
    for key in (
        "title", "subtitle", "description_ko", "description_en",
        "include_lyrics_in_description", "tags", "hashtags", "tracks", "description_locked",
    ):
        if key in payload:
            yt[key] = payload[key]
    if "hashtags" in yt or "tags" in yt:
        if "tags" in payload:
            yt["tags"] = resolve_youtube_tags(yt.get("tags"))
        yt["hashtags"] = resolve_youtube_hashtags(
            yt.get("hashtags"),
            yt.get("tags"),
        )

    if payload.get("mode"):
        editor["mode"] = payload["mode"]
    if len(editor.get("project_paths") or []) >= 2:
        editor["mode"] = "playlist"

    preview = payload.get("description_preview")
    rebuild = payload.get("description_locked") is False
    use_preview = isinstance(preview, str) and not rebuild
    yt["description_locked"] = bool(use_preview)
    title_txt = (yt.get("title") or "").strip()
    save_editor_config(project_dir, editor)

    assets = find_project_assets(project_dir)
    if editor.get("mode") == "playlist":
        tracks = ensure_playlist_tracks(project_dir, editor)
        editor = load_editor_config(project_dir)
        yt = editor.get("youtube") or yt
        auto = _auto_block_text(yt, editor, tracks)
        if use_preview:
            text = preview
        else:
            text = _playlist_description_text(
                yt.get("title") or assets.get("track_title") or project_dir.name,
                yt.get("subtitle") or "",
                yt,
                editor,
                tracks,
            )
    else:
        from app.services.pipeline_service import probe_duration

        audio = (assets.get("audio_paths") or [None])[0]
        runtime = probe_duration(Path(audio)) if audio else 0.0
        auto = _auto_block_text(
            yt,
            editor,
            [],
            single_title=assets.get("track_title") or yt.get("title") or project_dir.name,
            runtime=runtime,
        )
        if use_preview:
            text = preview
        else:
            text = build_single_description(project_dir, yt, assets, editor)

    (project_dir / YOUTUBE_DESC_FILE).write_text(text[:5000], encoding="utf-8")
    if title_txt:
        (project_dir / "title.txt").write_text(title_txt, encoding="utf-8")

    return {"ok": True, "description": text, "auto_block": auto, "char_count": len(text)}


def regenerate_playlist_chapters(project_dir: Path, project_paths: list[str]) -> list[dict]:
    """합본 트랙 챕터 초안 — 각 프로젝트 제목 + 누적 시작 시각."""
    from app.services.pipeline_service import probe_duration

    tracks: list[dict] = []
    cursor = 0.0
    for i, rel in enumerate(project_paths, start=1):
        p = Path(rel)
        assets = find_project_assets(p)
        audio = assets.get("audio_paths") or []
        dur = probe_duration(Path(audio[0])) if audio else 180.0
        title = assets.get("track_title") or p.name
        tracks.append(
            {
                "index": i,
                "title": title,
                "start_sec": round(cursor, 2),
                "duration_sec": round(dur, 2),
                "manual": False,
            }
        )
        cursor += dur
    editor = load_editor_config(project_dir)
    editor.setdefault("youtube", {})["tracks"] = tracks
    save_editor_config(project_dir, {"youtube": editor["youtube"], "project_paths": project_paths})
    return tracks


def apply_thumbnail_to_project(project_dir: Path, thumb_src: Path) -> Path:
    dest = project_dir / "thumbnail.jpg"
    tmp = project_dir / "thumbnail.jpg.tmp"
    shutil.copy2(thumb_src, tmp)
    tmp.replace(dest)
    return dest


def generate_thumbnail_preview(
    project_dir: Path,
    editor: dict,
    out_path: Path,
    *,
    assets: dict | None = None,
    preview_fast: bool = False,
) -> Path:
    assets = assets or find_project_assets(project_dir)
    thumb = editor.get("thumbnail") or {}
    boxes = thumb.get("boxes")
    if thumb.get("layout") == "canvas" and isinstance(boxes, list) and len(boxes) > 0:
        canvas_thumb = thumb
    else:
        canvas_thumb = _ensure_thumbnail_canvas({"thumbnail": thumb}, project_dir, assets)["thumbnail"]
    return render_thumbnail_canvas(
        project_dir,
        canvas_thumb,
        out_path,
        assets=assets,
        preview_fast=preview_fast,
    )


def generate_subtitle_preview_frame(
    project_dir: Path,
    config: dict,
    out_path: Path,
    *,
    sample_cue: dict | None = None,
) -> Path:
    from app.services.ass_subtitle_service import build_whick_ass, infer_album_and_track
    from app.services.pipeline_service import build_subtitles_vf, make_cover_frame

    assets = find_project_assets(project_dir)
    images = assets.get("image_paths") or []
    if not images:
        raise ValueError("미리보기용 이미지가 없습니다")
    w = int(config.get("video", {}).get("width", 1920))
    h = int(config.get("video", {}).get("height", 1080))

    cue = sample_cue or {
        "start": 2.0,
        "end": 8.0,
        "en": "Sample lyric line in English",
        "ko": "샘플 가사 한 줄",
    }
    title = assets.get("track_title") or project_dir.name
    album, idx = infer_album_and_track(project_dir)
    ass = build_whick_ass(
        track_title=title,
        duration_sec=12.0,
        cues=[cue],
        config=config,
        album=album,
        track_index=idx,
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        frame = tmp_path / "frame.jpg"
        ass_path = tmp_path / "sub.ass"
        make_cover_frame(Path(images[0]), frame, bg_w=w, bg_h=h)
        ass_path.write_text(ass, encoding="utf-8")
        sub_vf = build_subtitles_vf(ass_path)
        _run_ffmpeg([
            "ffmpeg", "-y",
            "-loop", "1", "-t", "1", "-i", str(frame),
            "-vf", sub_vf,
            "-frames:v", "1",
            str(out_path),
        ])
    return out_path


def generate_video_cover_frame(project_dir: Path, out_path: Path) -> Path:
    """실제 영상과 동일한 블러 배경 + 중앙 커버 프레임."""
    from app.services.pipeline_service import make_cover_frame

    assets = find_project_assets(project_dir)
    images = assets.get("cover_image_paths") or [
        p for p in (assets.get("image_paths") or [])
        if Path(p).name.lower() != "thumbnail.jpg"
    ] or (assets.get("image_paths") or [])
    if not images:
        raise ValueError("커버 이미지가 없습니다")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return make_cover_frame(Path(images[0]), out_path, bg_w=1920, bg_h=1080)


def _folder_match_key(name: str) -> str:
    from app.services.workflow_service import _review_album_key

    return _review_album_key(_TRACK_NUM_RE.sub("", (name or "").strip())).strip().lower()


def _folders_match(project_name: str, folder_name: str) -> bool:
    a, b = _folder_match_key(project_name), _folder_match_key(folder_name)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def find_latest_video(
    project_dir: Path,
    *,
    preview: bool = False,
    work_root: Path | None = None,
) -> Path | None:
    if preview:
        for name in (PREVIEW_VIDEO_NAME, "preview_30s.mp4"):
            p = project_dir / name
            if p.exists():
                return p
        return None
    skip = PREVIEW_VIDEO_NAMES
    from app.services.workflow_service import load_last_pipeline_video

    last = load_last_pipeline_video(project_dir)
    if last and last.name.lower() not in skip:
        return last

    mp4s: list[Path] = [
        p for p in project_dir.rglob("*.mp4")
        if p.name.lower() not in skip
    ]
    # 풀 인코딩 결과는 검수대기 등 스테이지 폴더로 옮겨짐
    if work_root is not None:
        from app.services.pipeline_defaults import WORKFLOW_STAGES

        name = project_dir.name
        for stage in WORKFLOW_STAGES:
            stage_dir = Path(work_root) / stage["folder"]
            if not stage_dir.is_dir():
                continue
            for folder in stage_dir.iterdir():
                if not folder.is_dir():
                    continue
                if not _folders_match(name, folder.name):
                    continue
                for p in folder.glob("*.mp4"):
                    if p.name.lower() not in skip:
                        mp4s.append(p)
    unique: list[Path] = []
    seen: set[str] = set()
    for p in mp4s:
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    unique.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return unique[0] if unique else None


def render_subtitle_preview_video(
    project_dir: Path,
    global_config: dict,
    *,
    duration_sec: float = PREVIEW_DURATION_SEC,
) -> Path:
    """자막·스펙트럼 위치 확인용 짧은 미리보기 영상 (Whisper 생략, 빠른 인코딩)."""
    from app.services.lyric_timing_service import (
        _cache_key,
        _load_cache,
        _pair_ko,
        _vocal_window_cues,
        prepare_sung_lines,
    )
    from app.services.pipeline_service import build_ass_content, probe_duration

    cfg = merge_editor_into_pipeline(project_dir, global_config)
    assets = find_project_assets(project_dir)
    if not assets.get("audio_paths"):
        raise ValueError("음원이 없습니다")
    audio_in = Path(assets["audio_paths"][0])
    covers = assets.get("cover_image_paths") or [
        p for p in (assets.get("image_paths") or [])
        if Path(p).name.lower() != "thumbnail.jpg"
    ] or (assets.get("image_paths") or [])
    if not covers:
        raise ValueError("이미지가 없습니다")
    cover_path = Path(covers[0])

    title = assets.get("track_title") or project_dir.name
    full_dur = probe_duration(audio_in)
    clip_dur = min(float(duration_sec), full_dur)

    lines, ko_lines, _ = prepare_sung_lines(assets.get("lyrics_en"), assets.get("lyrics_ko"))
    cache_path = project_dir / "lyrics_timing.json"
    key = _cache_key(audio_in, lines, source_path=audio_in)
    cached = _load_cache(cache_path, key, full_dur) if lines else None
    if cached:
        timed = _pair_ko(cached, ko_lines)
    elif lines:
        timed = _vocal_window_cues(lines, ko_lines, clip_dur)
    else:
        timed = []
    timed = [c for c in timed if float(c.get("start", 0)) < clip_dur]

    cfg_with_cues = {**cfg, "_timed_cues": timed}
    from app.services.ass_subtitle_service import infer_album_and_track

    album, idx = infer_album_and_track(project_dir)
    cfg_with_cues["_album"] = album
    cfg_with_cues["_track_index"] = idx
    ass_content = build_ass_content(
        title,
        assets.get("lyrics_en"),
        assets.get("lyrics_ko"),
        clip_dur,
        cfg_with_cues,
    )
    ass_path = project_dir / "_preview_subtitles.ass"
    ass_path.write_text(ass_content, encoding="utf-8")

    out_path = project_dir / PREVIEW_VIDEO_NAME
    _encode_preview_clip(
        audio_in,
        cover_path,
        ass_path,
        out_path,
        duration_sec=clip_dur,
        overlay=cfg.get("overlay") or {},
    )
    return out_path


def _encode_preview_clip(
    audio_path: Path,
    image_path: Path,
    ass_path: Path,
    out_path: Path,
    *,
    duration_sec: float,
    overlay: dict | None = None,
) -> Path:
    """자막·스펙트럼 위치 확인용 저화질 1패스. 리마스터/Whisper 없음."""
    from app.services.pipeline_service import build_subtitles_vf, find_ffmpeg, make_cover_frame

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg가 설치되어 있지 않습니다.")

    pw, ph, fps = 854, 480, 12
    cover = Path(image_path)
    if not cover.exists():
        raise ValueError("커버 이미지가 없습니다")

    ov = overlay or {}
    eq_style = str(ov.get("eq_bar_style", "none"))
    eq_enabled = eq_style not in ("none", "off", "") and bool(ov.get("eq_bar_enabled", True))
    sx = pw / 1920.0
    sy = ph / 1080.0
    eq_w = max(8, round(int(ov.get("eq_bar_w", 1000)) * sx))
    eq_h = max(8, round(int(ov.get("eq_bar_h", 80)) * sy))
    eq_color = str(ov.get("eq_bar_color") or "#FFFFFF")
    eq_align = str(ov.get("eq_bar_align") or "bottom_center")
    if eq_align == "bottom_center":
        eq_x = max(0, (pw - eq_w) // 2)
        eq_y = max(0, ph - eq_h - max(8, round(24 * sy)))
    else:
        eq_x = int(int(ov.get("eq_bar_x", 460)) * sx)
        eq_y = int(int(ov.get("eq_bar_y", 980)) * sy)
        eq_x = max(0, min(eq_x, max(0, pw - eq_w)))
        eq_y = max(0, min(eq_y, max(0, ph - eq_h)))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        bg = tmp_path / "bg.jpg"
        make_cover_frame(cover, bg, bg_w=pw, bg_h=ph)
        ass_local = tmp_path / "sub.ass"
        shutil.copyfile(ass_path, ass_local)
        sub_vf = build_subtitles_vf(ass_local)

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
                max_duration=duration_sec,
                fps=fps,
                color=eq_color,
            )

        wm = None
        try:
            from app.services.watermark_service import (
                prepare_watermark_png,
                watermark_overlay_fc,
                watermark_xy,
            )

            wm = prepare_watermark_png(tmp_path / "watermark.png", video_h=ph)
            wx, wy = watermark_xy(pw, ph)
        except Exception:
            wm = None
            wx, wy = 16, 12

        if has_eq:
            from app.services.pipeline_service import _eq_overlay_fc

            pad = max(8, round(24 * sy))
            eq_fc = _eq_overlay_fc(
                eq_w,
                eq_h,
                align=eq_align,
                eq_x=eq_x,
                eq_y=eq_y,
                bottom_pad=pad,
                main="[base]",
                out="v1",
                yuv=False,
            )
            extra = ["-i", str(eq_path)]
            next_i = 2
            fc = (
                f"[0:v]format=yuv420p[base];"
                f"{eq_fc};"
                f"[v1]{sub_vf}[vsub]"
            )
            if wm:
                extra += ["-i", str(wm)]
                fc += ";" + watermark_overlay_fc("[vsub]", f"[{next_i}:v]", "outv", x=wx, y=wy)
                next_i += 1
            else:
                fc += ";[vsub]format=yuv420p[outv]"
            extra += ["-i", str(audio_path), "-t", str(duration_sec)]
            cmd = [
                ffmpeg, "-y",
                "-loop", "1", "-framerate", str(fps), "-t", str(duration_sec), "-i", str(bg),
                *extra,
                "-filter_complex", fc,
                "-map", "[outv]", "-map", f"{next_i}:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32",
                "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-ar", "22050",
                "-shortest",
                "-movflags", "+faststart",
                str(out_path),
            ]
        else:
            extra = []
            next_i = 1
            fc = f"[0:v]format=yuv420p,{sub_vf}[vsub]"
            if wm:
                extra += ["-i", str(wm)]
                fc += ";" + watermark_overlay_fc("[vsub]", "[1:v]", "outv", x=wx, y=wy)
                next_i = 2
            else:
                fc += ";[vsub]format=yuv420p[outv]"
            extra += ["-i", str(audio_path), "-t", str(duration_sec)]
            cmd = [
                ffmpeg, "-y",
                "-loop", "1", "-framerate", str(fps), "-t", str(duration_sec), "-i", str(bg),
                *extra,
                "-filter_complex", fc,
                "-map", "[outv]", "-map", f"{next_i}:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32",
                "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-ar", "22050",
                "-shortest",
                "-movflags", "+faststart",
                str(out_path),
            ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "")[-2000:]
            raise RuntimeError(f"미리보기 인코딩 실패: {err}")
    return out_path
