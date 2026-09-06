# -*- coding: utf-8 -*-
"""인코딩 사전 점검 (preflight).

인코딩 시작 전/자막 정렬 후에 문제를 감지하면 즉시 중단하고
원인을 사용자가 읽을 수 있는 한국어 메시지로 알린다.

검증 항목:
  [트랙 자산] 음원 / 고유 커버 / 가사 존재 + 실제 읽히는지
  [정렬 결과] 큐 0개 트랙 / 가사 줄 대비 커버리지 / 역전·과장 겹침·트랙 경계 초과
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.services.workflow_service import find_project_assets, pick_track_playlist_cover


class PreflightError(ValueError):
    """사전 점검 실패 — message에 문제 목록이 줄바꿈으로 들어간다."""


_HEADER = "사전 점검 실패 — 인코딩을 중단합니다"
_MAX_SHOWN = 8


def _fail(problems: list[str]) -> None:
    """문제 목록으로 PreflightError 발생 (길면 앞 8개만 표시)."""
    lines = [f"• {p}" for p in problems[:_MAX_SHOWN]]
    if len(problems) > _MAX_SHOWN:
        lines.append(f"• 외 {len(problems) - _MAX_SHOWN}개 문제 더 있음")
    raise PreflightError(_HEADER + "\n" + "\n".join(lines))


def _is_blank(text: str | None) -> bool:
    return not (text or "").strip()


def count_lyric_lines(lyrics: str | None) -> int:
    """가사 줄 수 — 빈 줄/섹션 태그([Verse] 등) 제외."""
    if _is_blank(lyrics):
        return 0
    n = 0
    for raw in (lyrics or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("["):
            continue
        n += 1
    return n


def preflight_track_assets(
    project_dirs: list[Path], subtitle_mode: str | None = None
) -> list[str]:
    """합본용: 각 트랙의 음원·커버·가사 존재 검사. 문제 목록 반환(빈 리스트=통과).

    subtitle_mode: "both"|"en"|"ko" — 모드에 필요한 언어 가사 파일도 검사.
    None이면 파일 존재만 검사(모드 미지정).
    """
    problems: list[str] = []
    mode = (subtitle_mode or "").strip().lower()
    need_en = mode in ("both", "en")
    need_ko = mode in ("both", "ko")

    for i, d in enumerate(project_dirs):
        num = i + 1
        assets = find_project_assets(d)

        # 1) 음원
        if not assets.get("audio_paths"):
            problems.append(f"{num}번 [{d.name}]: 음원 파일 없음 (wav/mp3/flac 등)")

        # 2) 고유 커버 — thumbnail.jpg(유튜브 목록용 생성물)는 제외하고 판정.
        #    또한 파일이 실제로 열리는지(손상 여부)도 확인.
        cover = pick_track_playlist_cover(assets)
        if not cover:
            problems.append(
                f"{num}번 [{d.name}]: 곡 고유 커버 이미지 없음 "
                "(thumbnail.jpg는 유튜브 목록용이므로 제외 — 원본 커버를 폴더에 넣어주세요)"
            )
        else:
            try:
                from PIL import Image

                with Image.open(cover) as im:
                    im.verify()
            except Exception:
                problems.append(f"{num}번 [{d.name}]: 커버 이미지 손상 — 파일을 열 수 없음: {cover.name}")

        # 3) 가사 — en/ko 중 최소 하나는 실내용 있어야 함 (기본 검사)
        en = assets.get("lyrics_en")
        ko = assets.get("lyrics_ko")
        has_en = count_lyric_lines(en) > 0
        has_ko = count_lyric_lines(ko) > 0
        if not has_en and not has_ko:
            problems.append(
                f"{num}번 [{d.name}]: 가사 파일 없음 또는 내용 비어 있음 "
                "(lyrics_en.txt 또는 lyrics_ko.txt 필요)"
            )
            continue

        # 4) 자막 모드별 검사 — 모드에 필요한 언어 가사가 없으면 자막이 반쪽 나옴
        if mode:
            if need_en and not has_en:
                problems.append(
                    f"{num}번 [{d.name}]: 자막 모드가 '{mode}'인데 영어 가사(lyrics_en.txt) 없음 "
                    "— 영어 자막이 빠진 채 인코딩됩니다. lyrics_en.txt를 넣거나 자막 모드를 바꿔주세요"
                )
            if need_ko and not has_ko:
                problems.append(
                    f"{num}번 [{d.name}]: 자막 모드가 '{mode}'인데 한국어 가사(lyrics_ko.txt) 없음 "
                    "— 한국어 자막이 빠진 채 인코딩됩니다. lyrics_ko.txt를 넣거나 자막 모드를 바꿔주세요"
                )

    return problems


def preflight_playlist_tracks(project_dirs: list[Path], subtitle_mode: str | None = None) -> None:
    """합본 시작 전 자산 점검 — 문제 있으면 즉시 중단."""
    problems = preflight_track_assets(project_dirs, subtitle_mode)
    if problems:
        _fail(problems)


def preflight_single_track(project_dir: Path, subtitle_mode: str | None = None) -> None:
    """단곡 시작 전 자산 점검 — 문제 있으면 즉시 중단."""
    problems = preflight_track_assets([project_dir], subtitle_mode)
    if problems:
        _fail(problems)


def _track_bounds(tracks: list[dict[str, Any]]) -> list[tuple[float, float, str]]:
    return [
        (float(t["start"]), float(t["end"]), str(t.get("title") or t.get("num") or "?"))
        for t in tracks
    ]


def _owner_track(st: float, bounds: list[tuple[float, float, str]]) -> tuple[float, float, str] | None:
    for s, e, name in bounds:
        if s <= st < e:
            return (s, e, name)
    return None


def validate_aligned_cues(
    cues: list[dict[str, Any]],
    tracks: list[dict[str, Any]],
    *,
    min_coverage: float = 0.7,
) -> None:
    """정렬 완료 후(절대 타임라인) 검증 — 인코딩 전에 문제 잡고 중단.

    cues: [{start, end, en, ko, track, ...}] 절대 시각
    tracks: [{start, end, title, lyrics_en, lyrics_ko, ...}]
    """
    problems: list[str] = []
    bounds = _track_bounds(tracks)

    # 1) 트랙별 큐 개수/커버리지
    by_track: dict[str, list[dict[str, Any]]] = {}
    for c in cues:
        own = _owner_track(float(c["start"]), bounds)
        key = own[2] if own else "(경계 밖)"
        by_track.setdefault(key, []).append(c)

    for s, e, name in bounds:
        got = len(by_track.get(name) or [])
        t = next((t for t in tracks if str(t.get("title") or "") == name), None)
        if t is None:
            continue
        en_lines = count_lyric_lines(t.get("lyrics_en"))
        ko_lines = count_lyric_lines(t.get("lyrics_ko"))
        expected = en_lines if en_lines > 0 else ko_lines
        if expected == 0:
            continue  # 가사 없는 트랙은 자산 점검에서 이미 차단
        if got == 0:
            problems.append(f"[{name}]: 자막 큐 0개 — 정렬 실패 (가사 {expected}줄)")
        elif got < expected * min_coverage:
            problems.append(
                f"[{name}]: 자막 커버리지 부족 — 가사 {expected}줄 중 {got}개만 정렬됨"
            )

    # 2) 기계적 결함 (역전 / 과장 겹침 / 트랙 경계 초과)
    cs = sorted(cues, key=lambda c: float(c["start"]))
    inv = ovl = overflow = 0
    ovl_names: dict[str, int] = {}
    overflow_names: dict[str, int] = {}
    for c in cs:
        st, en = float(c["start"]), float(c["end"])
        if en < st:
            inv += 1
        own = _owner_track(st, bounds)
        if own:
            s, e, name = own
            if en > e + 0.5:
                overflow += 1
                overflow_names[name] = overflow_names.get(name, 0) + 1
    for a, b in zip(cs, cs[1:]):
        if float(b["start"]) < float(a["end"]) - 1.5:
            ovl += 1
            own = _owner_track(float(b["start"]), bounds)
            name = own[2] if own else "?"
            ovl_names[name] = ovl_names.get(name, 0) + 1

    if inv:
        problems.append(f"자막 타임라인 역전 {inv}개 (start > end)")
    if ovl:
        detail = ", ".join(f"{k} {v}개" for k, v in sorted(ovl_names.items())[:3])
        problems.append(f"자막 과장 겹침 {ovl}개 (1.5초 초과 — {detail})")
    if overflow:
        detail = ", ".join(f"{k} {v}개" for k, v in sorted(overflow_names.items())[:3])
        problems.append(f"자막 트랙 경계 초과 {overflow}개 ({detail})")

    if problems:
        _fail(problems)
