"""유튜브 설명 블록 위젯 — 왼쪽: 넣을 수 있는 블록 목록 / 오른쪽: 사용자가 선택한 블록 순서.

블록 정의는 DESCR_BLOCKS(SSOT)에 있고, 실제 텍스트 생성은 각 블록 id에 매핑된
빌더 함수가 담당한다. brand.json의 desc_blocks(블록 id 목록)가 사용자 구성이며,
비어 있으면 DEFAULT_DESC_BLOCKS 순서를 따른다.
"""

from __future__ import annotations

from typing import Any, Callable

from app.services.brand_service import (
    brand_footer_text,
    brand_hashtag_defaults,
    brand_source_url,
    load_brand,
)


def captions_label(subtitle_mode: str | None) -> str:
    mode = (subtitle_mode or "both").lower()
    if mode == "en":
        return "English lyrics (on-screen)"
    if mode == "ko":
        return "Korean lyrics (on-screen)"
    return "English lyrics + Korean translation (on-screen)"


def format_ts(sec: float) -> str:
    """YouTube 챕터용 타임스탬프 (0:00 / 1:23:45)."""
    total = max(0, int(round(float(sec or 0))))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_hashtags(value: str | list | None, fallback: str) -> str:
    if isinstance(value, list):
        tokens = [str(x).strip() for x in value]
    else:
        raw = (value or "").strip()
        tokens = [p.strip() for p in raw.split(",")] if "," in raw else (raw.split() if raw else [])
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


# ---------- 블록 빌더 ----------


def _blk_intro(ctx: dict[str, Any]) -> str:
    """직접 입력 소개 (영어+한글)."""
    parts: list[str] = []
    en = (ctx.get("description_en") or "").strip()
    ko = (ctx.get("description_ko") or "").strip()
    if en:
        parts.append(en)
    if ko and ko != en:
        parts.append(ko)
    return "\n\n".join(parts)


def _blk_tracklist(ctx: dict[str, Any]) -> str:
    tracks = ctx.get("tracks") or []
    parts = ["🎵 Tracklist"]
    if tracks:
        for t in tracks:
            name = (t.get("title") or "").strip() or "Untitled"
            start = float(t.get("start") or t.get("start_sec") or 0)
            parts.append(f"{format_ts(start)} {name}")
    else:
        parts.append("0:00")
    return "\n".join(parts)


def _blk_specs(ctx: dict[str, Any]) -> str:
    tracks = ctx.get("tracks") or []
    n = len(tracks)
    if tracks:
        last = tracks[-1]
        start = float(last.get("start") or last.get("start_sec") or 0)
        dur = float(last.get("duration") or last.get("duration_sec") or 0)
        runtime = format_ts(start + dur if dur > 0 else start)
    else:
        runtime = format_ts(ctx.get("runtime") or 0)
    parts = [
        "◎ Album specs",
        f"Tracks: {n} · Runtime: {runtime}",
        "Audio: Studio remaster (AI-assisted)",
        f"Captions: {captions_label(ctx.get('subtitle_mode'))}",
    ]
    src_url = (ctx.get("source_url") or "").strip() or brand_source_url()
    if src_url:
        parts.append(f"Source: {src_url}")
    return "\n".join(parts)


def _blk_copyright(ctx: dict[str, Any]) -> str:
    return brand_footer_text()


def _blk_hashtags(ctx: dict[str, Any]) -> str:
    _, default_hashtags = brand_hashtag_defaults()
    fallback = default_hashtags or "#Playlist, #Acoustic, #Instrumental, #StudyMusic"
    return _fmt_hashtags(ctx.get("hashtags") or ctx.get("tags"), fallback)


def _blk_lyrics(ctx: dict[str, Any]) -> str:
    if not ctx.get("include_lyrics_in_description"):
        return ""
    ko = ctx.get("lyrics_ko") or ""
    en = ctx.get("lyrics_en") or ""
    if ko:
        return f"[가사]\n{ko[:2500]}"
    if en:
        return f"[Lyrics]\n{en[:2500]}"
    return ""


def _blk_custom(ctx: dict[str, Any]) -> str:
    """사용자 자유 블록 — brand.json의 custom_desc_block 텍스트."""
    return (load_brand().get("custom_desc_block") or "").strip()


def _blk_album_title(ctx: dict[str, Any]) -> str:
    """앨범(업로드) 제목 — 챕터 인식용 헤딩. 빈 값이면 블록 생략."""
    return (ctx.get("album_title") or "").strip()


# ---------- SSOT: 넣을 수 있는 블록 정의 ----------

DESCR_BLOCKS: dict[str, dict[str, Any]] = {
    "album_title": {
        "label": "앨범 제목",
        "hint": "업로드 제목 (6단계에서 입력)",
        "builder": _blk_album_title,
    },
    "intro": {
        "label": "소개 (직접 입력)",
        "hint": "6단계에서 입력한 영어·한글 소개",
        "builder": _blk_intro,
    },
    "tracklist": {
        "label": "트랙리스트 (챕터)",
        "hint": "곡 시작 시각 + 제목 자동 생성",
        "builder": _blk_tracklist,
    },
    "specs": {
        "label": "앨범 스펙",
        "hint": "트랙 수·재생시간·자막 정보·소스 URL",
        "builder": _blk_specs,
    },
    "copyright": {
        "label": "저작권 문구",
        "hint": "브랜드 설정의 © 문구",
        "builder": _blk_copyright,
    },
    "hashtags": {
        "label": "해시태그",
        "hint": "브랜드 기본 해시태그 또는 저장된 태그",
        "builder": _blk_hashtags,
    },
    "lyrics": {
        "label": "전체 가사",
        "hint": "'가사 포함'을 켰을 때만 내용이 들어감",
        "builder": _blk_lyrics,
    },
    "custom": {
        "label": "자유 블록",
        "hint": "사용자 설정에서 직접 작성한 고정 문구",
        "builder": _blk_custom,
    },
}

DEFAULT_DESC_BLOCKS = ["album_title", "intro", "tracklist", "specs", "copyright", "hashtags"]


def available_blocks() -> list[dict[str, str]]:
    """위젯 왼쪽: 넣을 수 있는 모든 블록."""
    return [
        {"id": bid, "label": b["label"], "hint": b["hint"]}
        for bid, b in DESCR_BLOCKS.items()
    ]


def selected_blocks() -> list[str]:
    """위젯 오른쪽: 사용자가 선택한 블록 id 순서. 유효하지 않은 id는 제거."""
    b = load_brand()
    ids = [str(x).strip() for x in (b.get("desc_blocks") or [])]
    valid = [i for i in ids if i in DESCR_BLOCKS]
    return valid or list(DEFAULT_DESC_BLOCKS)


def build_description_from_blocks(ctx: dict[str, Any], block_ids: list[str] | None = None) -> str:
    """선택된 블록 순서대로 설명 전체를 조립. 빈 블록은 건너뛴다."""
    ids = [i for i in (block_ids or selected_blocks()) if i in DESCR_BLOCKS]
    chunks: list[str] = []
    for bid in ids:
        try:
            text = (DESCR_BLOCKS[bid]["builder"](ctx) or "").strip()
        except Exception:
            text = ""
        if text:
            chunks.append(text)
    return "\n\n".join(chunks)[:4900]
