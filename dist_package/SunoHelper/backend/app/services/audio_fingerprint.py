"""Suno 오디오/영상 지문 검사 — WHICK assert_no_suno_fingerprint 이식."""

from __future__ import annotations

import subprocess
from pathlib import Path


def probe_metadata_blob(media_path: Path) -> str:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_format", "-show_streams", str(media_path)],
        capture_output=True,
        text=True,
        encoding="utf-8", errors="replace",
        timeout=120,
    )
    return ((r.stdout or "") + (r.stderr or "")).lower()


def has_suno_fingerprint(media_path: Path) -> bool:
    if not media_path.is_file():
        return False
    return "suno" in probe_metadata_blob(media_path)


def assert_no_suno_fingerprint(media_path: Path) -> None:
    """업로드 전 안전장치 — Suno 메타가 남아 있으면 중단."""
    if has_suno_fingerprint(media_path):
        raise ValueError(
            f"Suno 지문(메타데이터)이 남아 있습니다. 리마스터 후 다시 시도하세요: {media_path.name}"
        )
