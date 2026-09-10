#!/usr/bin/env python3
"""
Listen-align SSOT — AI가 실제 오디오를 듣고 가사 타이밍을 붙인다.

균등 배치·깨진 fuzzy segment 매칭 금지.
faster-whisper word_timestamps + 순차 윈도우 매칭.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any


def norm_tok(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def is_sung_english_line(line: str) -> bool:
    """BPM/Story/한글설명/제목/연주큐 제외 — 가창 영문만."""
    s = (line or "").strip()
    if len(s) < 3:
        return False
    hangul = len(re.findall(r"[가-힣]", s))
    latin = len(re.findall(r"[A-Za-z]", s))
    if hangul > latin:
        return False
    if latin < 3:
        return False
    low = s.lower().strip()
    if low in ("story", "lyrics", "가사", "chorus", "verse", "bridge", "outro", "intro"):
        return False
    if "bpm" in low:
        return False
    if re.search(r"약\s*\d+\s*분", s):
        return False
    if s.startswith("(") and s.endswith(")"):
        return False
    # "01. Track_Title" 메타 제목
    if re.match(r"^\d{1,2}\.\s+\S", s) and not re.search(
        r"\b(i|you|we|my|your|the|a|an|and|to|it|me|I'm|don't|can't)\b", s, re.I
    ):
        return False
    return True


def filter_sung_lines(en_lines: list[str], ko_lines: list[str] | None = None) -> tuple[list[str], list[str]]:
    ko_lines = ko_lines or []
    en_out, ko_out = [], []
    for i, en in enumerate(en_lines):
        if not is_sung_english_line(en):
            continue
        en_out.append(en)
        ko_out.append(ko_lines[i] if i < len(ko_lines) else "")
    return en_out, ko_out


def extract_whisper_words(
    whisper_model,
    audio_path: str,
    *,
    initial_prompt: str | None = None,
) -> list[dict[str, Any]]:
    # VAD 끄기: Silero VAD는 음성용이라 가창 보컬을 비음성으로 판정해
    # 단어 대량 누락(409→118개)을 일으킨다. 반주 섞인 노래는 VAD 없이 전사해야 함.
    #
    # temperature=0.0 고정 + condition_on_previous_text=True는 반복 후렴곡에서 치명적:
    # 모델이 앞서 전사한 후렴 텍스트를 뒤 구간(벌스/브릿지)에서 반복 출력하는
    # 환각 루프에 빠지고, temperature 폴백이 없어 빠져나오지 못한다.
    # (트랙9 사례: 벌스3 구간 168~200s에 후렴2 텍스트가 찍혀 umbrella/leaf/bass 등
    #  벌스3 단어가 전사 자체에서 소실 → 이후 줄 전부 연쇄 오배정)
    # → 이전 텍스트 조건화를 끄고, 기본 temperature 폴백 사다리로 루프 탈출.
    kwargs: dict[str, Any] = dict(
        language="en",
        beam_size=5,
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt[:400]
    segments, _ = whisper_model.transcribe(audio_path, **kwargs)
    words: list[dict[str, Any]] = []
    last_end = 0.0
    for seg in segments:
        if not seg.words:
            tok = (seg.text or "").strip()
            if tok:
                words.append({"start": float(seg.start), "end": float(seg.end), "word": tok})
            continue
        for w in seg.words:
            tok = (w.word or "").strip()
            if not tok:
                continue
            st = float(w.start)
            en = float(w.end)
            # whisper의 음수/역행 타임스탬프만 교정 (내부 단조화 금지 —
            # 세그먼트 경계 겹침이 실제 가창 겹침일 수 있고, 여기서 clamp하면
            # 반복 후렴 단어들이 한 점으로 뭉개져 매처가 순서를 잃는다.
            # 트랙9 사례: 183.48s에 단어 21개가 몰려 순차 매칭 연쇄 오배정)
            if st < 0:
                st = 0.0
            if en < st:
                en = st
            words.append({"start": st, "end": en, "word": tok})
    return words


def _window_text(words: list[dict], i: int, j: int) -> str:
    return "".join(norm_tok(w["word"]) for w in words[i:j])


def _retry_align(
    lines: list[str],
    words: list[dict[str, Any]],
    track_duration: float,
    raw: list[dict[str, Any] | None],
    cursor: int,
    li: int,
) -> int:
    """1차 매칭 실패 시 더 넓은 윈도우로 재시도. 성공 시 매칭된 word end index 반환, 실패 시 -1."""
    target = norm_tok(lines[li])
    if not target:
        return -1
    n_w = len(words)
    remain_lines = len(lines) - li
    remain_words = max(1, n_w - cursor)
    approx = max(2, int(remain_words / remain_lines))
    best = None
    search_limit = min(n_w, cursor + max(60, approx * 12))
    # 재시도도 시간 폭 상한 적용 (메가큐/커서 대점프 방지 — align_lines_to_words와 동일)
    max_time = float(words[cursor]["start"]) + 30.0 if cursor < n_w else float("inf")
    for i in range(cursor, search_limit):
        wst = float(words[i]["start"])
        if wst > max_time:
            break
        for win in range(max(1, approx - 5), approx + 14):
            j = i + win
            if j > n_w:
                break
            if float(words[j - 1]["end"]) - float(words[i]["start"]) > 30.0:
                break
            got = _window_text(words, i, j)
            if not got:
                continue
            if len(got) < max(2, int(len(target) * 0.25)):
                continue
            if len(got) > int(len(target) * 3.5) + 12:
                continue
            score = SequenceMatcher(None, target, got).ratio()
            if best is None or score > best[0]:
                best = (score, i, j)
    if best and best[0] >= 0.20:
        score, i, j = best
        st = float(words[i]["start"])
        en = float(words[j - 1]["end"])
        raw[li] = {
            "start": round(st, 2),
            "end": round(min(track_duration - 0.4, max(en, st + 1.8)), 2),
            "text": lines[li],
            "score": round(score, 3),
            "method": "listen_retry",
        }
        return j
    return -1


def align_lines_to_words(
    lines: list[str],
    words: list[dict[str, Any]],
    track_duration: float,
    audio_path: str | None = None,
) -> list[dict[str, Any]]:
    """공식 가사 줄을 Whisper 단어열에 순차로 붙인다."""
    if not lines:
        return []
    if not words:
        return _energy_fallback(lines, [], track_duration, audio_path)

    n_w = len(words)
    cursor = 0
    raw: list[dict[str, Any] | None] = [None] * len(lines)

    for li, line in enumerate(lines):
        target = norm_tok(line)
        if not target:
            continue
        # 남은 줄 수 대비 남은 단어
        remain_lines = len(lines) - li
        remain_words = max(1, n_w - cursor)
        approx = max(2, int(remain_words / remain_lines))
        best = None  # (score, i, j)
        search_limit = min(n_w, cursor + max(40, approx * 8))
        # 최대 탐색 시각: 커서에서 가사 한 줄 검색에 합리적인 상한(25초).
        # 이걸 넘는 매칭은 커서가 실제 가창 위치를 크게 건너뛴 것 →
        # (트랙9 사례: 20.66s짜리 메가큐가 뒷줄 매칭을 연쇄적으로 밀어냄)
        max_time = float(words[cursor]["start"]) + 25.0 if cursor < n_w else float("inf")
        for i in range(cursor, search_limit):
            wst = float(words[i]["start"])
            if wst > max_time:
                break
            for win in range(max(1, approx - 3), approx + 8):
                j = i + win
                if j > n_w:
                    break
                # 창의 시간 폭도 제한 (단어 밀도가 낮은 구간의 메가큐 방지)
                if float(words[j - 1]["end"]) - float(words[i]["start"]) > 25.0:
                    break
                got = _window_text(words, i, j)
                if not got:
                    continue
                # length guard
                if len(got) < max(3, int(len(target) * 0.35)):
                    continue
                if len(got) > int(len(target) * 2.8) + 8:
                    continue
                score = SequenceMatcher(None, target, got).ratio()
                if best is None or score > best[0]:
                    best = (score, i, j)

        if best and best[0] >= 0.35:
            score, i, j = best
            st = float(words[i]["start"])
            en = float(words[j - 1]["end"])
            if en - st < 1.8:
                en = min(track_duration - 0.4, st + 3.0)
            # feasibility: 뒤에 남은 줄이 이 매칭 뒤쪽에 배치될 공간이 있는지
            # (반복 후렴이 곡 끝에서 오탐매칭되면 남은 줄이 트랙을 넘어섬)
            remain_after = len(lines) - li - 1
            if st + remain_after * 1.9 + 2.0 > track_duration:
                raw[li] = None
                continue
            raw[li] = {
                "start": round(st, 2),
                "end": round(min(track_duration - 0.4, en), 2),
                "text": line,
                "score": round(score, 3),
                "method": "listen",
            }
            cursor = j
        else:
            # 약한 매칭이라도 전진 (최소 0.25)
            if best and best[0] >= 0.25:
                score, i, j = best
                st = float(words[i]["start"])
                en = float(words[j - 1]["end"])
                remain_after = len(lines) - li - 1
                if st + remain_after * 1.9 + 2.0 > track_duration:
                    cursor = j
                    continue
                raw[li] = {
                    "start": round(st, 2),
                    "end": round(min(track_duration - 0.4, max(en, st + 1.8)), 2),
                    "text": line,
                    "score": round(score, 3),
                    "method": "listen_weak",
                }
                cursor = j
            # 2차 재시도 (더 넓은 윈도우)
            else:
                retry_j = _retry_align(lines, words, track_duration, raw, cursor, li)
                if retry_j >= 0:
                    cursor = retry_j
                else:
                    raw[li] = None

    # Fix cursor update for retry — re-scan raw to find last j
    cursor = 0
    for li, line in enumerate(lines):
        if raw[li] is not None:
            # find approximate end word index for this match
            en_t = float(raw[li]["end"])
            # advance cursor past words that end before this match ends
            while cursor < n_w and float(words[cursor]["end"]) <= en_t + 0.3:
                cursor += 1

    # 미매칭 구간: 양쪽 매칭 사이 시간으로 보간 (균등 전곡 배치 금지)
    aligned: list[dict[str, Any]] = []
    for li, line in enumerate(lines):
        if raw[li] is not None:
            aligned.append(raw[li])
            continue
        prev_i = next((k for k in range(li - 1, -1, -1) if raw[k] is not None), None)
        next_i = next((k for k in range(li + 1, len(lines)) if raw[k] is not None), None)
        if prev_i is not None and next_i is not None:
            gap_lines = next_i - prev_i
            pos = li - prev_i
            t0 = float(raw[prev_i]["end"])
            t1 = float(raw[next_i]["start"])
            if t1 <= t0 + 0.5:
                t1 = min(track_duration - 0.4, t0 + gap_lines * 3.0)
            st = t0 + (t1 - t0) * (pos / gap_lines)
            en = t0 + (t1 - t0) * ((pos + 0.75) / gap_lines)
        elif prev_i is not None:
            st = float(raw[prev_i]["end"]) + 0.5
            en = st + 3.5
        elif next_i is not None:
            en = float(raw[next_i]["start"]) - 0.3
            st = max(0.5, en - 3.5)
        else:
            return _energy_fallback(lines, words, track_duration, audio_path)
        st = max(0.0, min(float(st), track_duration - 2.0))
        en = max(st + 1.8, min(float(en), track_duration - 0.4))
        aligned.append(
            {
                "start": round(st, 2),
                "end": round(en, 2),
                "text": line,
                "score": 0.0,
                "method": "interp",
            }
        )
        raw[li] = aligned[-1]

    # 단조 증가 + 겹침 보정 (2-pass)
    for _ in range(2):
        for k in range(1, len(aligned)):
            if aligned[k]["start"] < aligned[k - 1]["start"] + 0.25:
                aligned[k]["start"] = round(aligned[k - 1]["start"] + 0.35, 2)
            if aligned[k]["start"] <= aligned[k - 1]["end"]:
                aligned[k - 1]["end"] = round(
                    max(aligned[k - 1]["start"] + 1.8, aligned[k]["start"] - 0.1), 2
                )

    # 중앙 관문: 역전/초과/겹침 절대 방지 (SSOT)
    return sanitize_cue_timeline(aligned, track_duration)


def _energy_fallback(
    lines: list[str],
    words: list[dict[str, Any]],
    track_duration: float,
    audio_path: str | None = None,
) -> list[dict[str, Any]]:
    """Whisper 단어가 없거나 전부 실패: librosa RMS 에너지 기반 보컬 구간 추정으로 각 줄 배치.

    실제 오디오의 에너지 프로파일(RMS)에서 조용한 구간(인트로/아웃트로/간주)을
    제외한 '소리 나는 구간' 안에만 가사를 배치한다. 에너지 분석 실패 시
    전곡의 15%~92% 구간을 추정 보컬 구간으로 사용.
    """
    try:
        import librosa
        import numpy as np
    except ImportError:
        librosa = None

    # 보컬 추정 구간 (에너지 분석 성공 시 실측으로 대체)
    v0 = min(20.0, track_duration * 0.15)
    v1 = max(v0 + 25.0, track_duration - 5.0)

    if librosa is not None and audio_path and track_duration > 5:
        try:
            y, sr = librosa.core.load(str(audio_path), sr=22050, mono=True)
            hop = 512
            rms = librosa.feature.rms(y=y, hop_length=hop)[0]
            times = librosa.frames_to_time(
                np.arange(len(rms)), sr=sr, hop_length=hop
            )
            thr = float(np.max(rms)) * 0.12
            loud = times[rms > thr]
            if len(loud) > 0:
                # 첫/마지막 '소리 나는' 시점 = 보컬+반주 활동 구간
                v0 = float(max(0.0, loud[0] - 1.0))
                v1 = float(min(track_duration, loud[-1] + 1.0))
        except Exception:
            pass  # 기본 v0/v1 유지

    # 에너지 분석이 실패한 경우에도 기본 구간은 보장 (이전 값 덮어쓰기 방지)
    v0 = max(0.0, min(v0, track_duration - 10.0))
    v1 = max(v0 + 15.0, min(v1, track_duration - 0.5))

    if not words:
        step = max(2.5, (v1 - v0) / max(1, len(lines)))
        out = []
        for i, line in enumerate(lines):
            st = v0 + i * step
            en = min(track_duration - 0.4, st + min(step * 0.88, 5.0))
            out.append(
                {
                    "start": round(st, 2),
                    "end": round(en, 2),
                    "text": line,
                    "score": 0.0,
                    "method": "energy_fallback",
                }
            )
        return out

    # words가 있으면 word span 내에 배치
    v0 = float(words[0]["start"]) if words else track_duration * 0.15
    v1 = float(words[-1]["end"]) if words else track_duration - 5.0
    if v1 - v0 < 10:
        v0 = track_duration * 0.15
        v1 = track_duration - 5.0
    step = max(2.5, (v1 - v0) / max(1, len(lines)))
    out = []
    for i, line in enumerate(lines):
        st = v0 + i * step
        en = min(track_duration - 0.4, st + min(step * 0.88, 5.0))
        out.append(
            {
                "start": round(st, 2),
                "end": round(en, 2),
                "text": line,
                "score": 0.0,
                "method": "energy_fallback",
            }
        )
    return out


def _interp_and_monotonic(
    lines: list[str],
    raw: list[dict[str, Any] | None],
    words: list[dict[str, Any]],
    track_duration: float,
    audio_path: str | None = None,
) -> list[dict[str, Any]]:
    """미매칭 보간 + 단조 증가 (순차/글로벌 공통)."""
    aligned: list[dict[str, Any]] = []
    raw = list(raw)
    for li, line in enumerate(lines):
        if raw[li] is not None:
            aligned.append(raw[li])
            continue
        prev_i = next((k for k in range(li - 1, -1, -1) if raw[k] is not None), None)
        next_i = next((k for k in range(li + 1, len(lines)) if raw[k] is not None), None)
        if prev_i is not None and next_i is not None:
            gap_lines = next_i - prev_i
            pos = li - prev_i
            t0 = float(raw[prev_i]["end"])
            t1 = float(raw[next_i]["start"])
            if t1 <= t0 + 0.5:
                t1 = min(track_duration - 0.4, t0 + gap_lines * 3.0)
            st = t0 + (t1 - t0) * (pos / gap_lines)
            en = t0 + (t1 - t0) * ((pos + 0.75) / gap_lines)
        elif prev_i is not None:
            st = float(raw[prev_i]["end"]) + 0.5
            en = st + 3.5
        elif next_i is not None:
            en = float(raw[next_i]["start"]) - 0.3
            st = max(0.5, en - 3.5)
        else:
            v0 = float(words[0]["start"]) if words else 20.0
            v1 = float(words[-1]["end"]) if words else track_duration - 5.0
            step = max(2.5, (v1 - v0) / max(1, len(lines)))
            st = v0 + li * step
            en = st + min(step * 0.88, 5.0)
        # 뒤에 이어질 줄 수까지 고려한 상한: 남은 줄이 최소 간격으로 들어갈 공간 확보
        tail_need = (len(lines) - li - 1) * 1.9
        st_cap = max(0.0, track_duration - 0.6 - tail_need)
        st = max(0.0, min(float(st), st_cap))
        en = max(st + 1.8, min(float(en), track_duration - 0.4))
        item = {
            "start": round(st, 2),
            "end": round(en, 2),
            "text": line,
            "score": 0.0,
            "method": "interp",
        }
        aligned.append(item)
        raw[li] = item

    # 단조 증가 + 겹침 보정 (2-pass) — 시작시각은 트랙 길이를 넘지 않게 clamp
    max_start = max(0.0, track_duration - 2.0)
    for _ in range(2):
        for k in range(1, len(aligned)):
            if aligned[k]["start"] < aligned[k - 1]["start"] + 0.25:
                aligned[k]["start"] = round(
                    min(max_start, aligned[k - 1]["start"] + 0.35), 2
                )
            if aligned[k]["start"] <= aligned[k - 1]["end"]:
                aligned[k - 1]["end"] = round(
                    max(aligned[k - 1]["start"] + 1.8, aligned[k]["start"] - 0.1), 2
                )
    # 중앙 관문: 역전/초과/겹침 절대 방지 (SSOT)
    return sanitize_cue_timeline(aligned, track_duration)


def sanitize_cue_timeline(
    cues: list[dict[str, Any]],
    track_duration: float,
    *,
    min_dur: float = 1.4,
    min_gap: float = 0.12,
    max_overlap_ratio: float = 0.4,
) -> list[dict[str, Any]]:
    """모든 가사 큐가 반드시 통과해야 하는 중앙 관문 (SSOT).

    보증:
      1. end > start (역전 금지) — 최소 min_dur 보장
      2. start/end가 트랙 길이 안에 존재 (초과 금지)
      3. 시작 시각 단조 증가
      4. 동시표시 겹침 금지: 새 큐가 이전 큐와 max_overlap_ratio 이상 겹치면
         이전 큐 end를 잘라내고, 그래도 공간이 없으면 이후 큐는 스킵
      5. 결정적(deterministic): 같은 입력 → 같은 출력

    어디서 왔든(Whisper seq/glob, 한국어 세그먼트, 캐시, 에너지 폴백, 보간)
    이 함수를 통과한 결과는 위 5가지를 위반할 수 없다.
    """
    if not cues:
        return []
    dur_limit = max(0.0, float(track_duration) - 0.2)

    # 1차: 역전/초과 교정 (복사본 생성 — 원본 오염 방지)
    fixed: list[dict[str, Any]] = []
    for c in cues:
        try:
            st = float(c["start"])
            en = float(c["end"])
        except (KeyError, TypeError, ValueError):
            continue
        # 음수 시각 교정 (Whisper/ffprobe 이상치)
        st = max(0.0, st)
        en = max(st, en)
        if en <= st:
            en = st + 2.2
        if en > dur_limit:
            en = dur_limit
            if en <= st:
                st = max(0.0, en - 2.2)
                en = st + 2.2
        if st >= dur_limit:
            continue  # 시작 자체가 불가능한 큐는 버림
        item = dict(c)
        item["start"] = st
        item["end"] = en
        fixed.append(item)

    # 2차: 시작 시각 정렬 후 겹침 해소
    fixed.sort(key=lambda x: float(x["start"]))
    kept: list[dict[str, Any]] = []
    prev_end = -1.0
    for c in fixed:
        st = float(c["start"])
        en = float(c["end"])
        if st < prev_end + min_gap:
            st = prev_end + min_gap
        # 겹침 해소 후 최소 표시시간 확보 불가 → 스킵 (자막 뭉개짐 방지)
        if st + min_dur > dur_limit:
            continue
        en = max(st + min_dur, min(en, dur_limit))
        # 이전 큐가 새 큐에 max_overlap_ratio 이상 침범하면 이전 큐 end 절단
        if kept:
            prev = kept[-1]
            if float(prev["end"]) > st and (float(prev["end"]) - st) > max_overlap_ratio * (float(prev["end"]) - float(prev["start"])):
                prev["end"] = round(st - 0.05, 2)
                if float(prev["end"]) <= float(prev["start"]) + 0.6:
                    # 이전 큐가 너무 짧아지면 그냥 이전 큐 유지, 현재 큐 스킵
                    st = float(prev["end"]) + min_gap
                    if st + min_dur > dur_limit:
                        continue
                    en = max(st + min_dur, min(en, dur_limit))
        c["start"] = round(st, 2)
        c["end"] = round(en, 2)
        prev_end = en
        kept.append(c)
    return kept


def _sanitize_final(aligned: list[dict[str, Any]], track_duration: float) -> list[dict[str, Any]]:
    """별칭: align_lines_to_words 계열의 마지막 안전망을 중앙 관문으로 교체."""
    return sanitize_cue_timeline(aligned, track_duration)


def align_lines_to_words_global(
    lines: list[str],
    words: list[dict[str, Any]],
    track_duration: float,
    audio_path: str | None = None,
) -> list[dict[str, Any]]:
    """가사 토큰 ↔ Whisper 단어 전역 SequenceMatcher (약곡에서 순차보다 강함)."""
    if not lines:
        return []
    if not words:
        return align_lines_to_words(lines, words, track_duration, audio_path)

    lyric_tokens: list[tuple[str, int]] = []
    for li, line in enumerate(lines):
        for p in re.findall(r"[A-Za-z0-9']+", line):
            n = norm_tok(p)
            if n:
                lyric_tokens.append((n, li))
    wh_norms: list[str] = []
    wh_idx: list[int] = []
    for i, w in enumerate(words):
        n = norm_tok(w["word"])
        if n:
            wh_norms.append(n)
            wh_idx.append(i)
    if not lyric_tokens or not wh_norms:
        return align_lines_to_words(lines, words, track_duration, audio_path)

    sm = SequenceMatcher(a=[t[0] for t in lyric_tokens], b=wh_norms, autojunk=False)
    line_times: dict[int, list[dict[str, Any]]] = {i: [] for i in range(len(lines))}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for a, b in zip(range(i1, i2), range(j1, j2)):
                line_times[lyric_tokens[a][1]].append(words[wh_idx[b]])
        elif tag == "replace" and j2 > j1 and i2 > i1:
            for k, a in enumerate(range(i1, i2)):
                b_idx = j1 + min(j2 - j1 - 1, int(k * (j2 - j1) / max(1, i2 - i1)))
                line_times[lyric_tokens[a][1]].append(words[wh_idx[b_idx]])

    raw: list[dict[str, Any] | None] = [None] * len(lines)
    for li, line in enumerate(lines):
        ts = line_times[li]
        if not ts:
            continue
        st = float(ts[0]["start"])
        en = float(ts[-1]["end"])
        if en < st + 1.8:
            en = min(track_duration - 0.4, st + 3.0)
        raw[li] = {
            "start": round(st, 2),
            "end": round(min(track_duration - 0.4, en), 2),
            "text": line,
            "score": 1.0,
            "method": "listen_global",
        }
    return _interp_and_monotonic(lines, raw, words, track_duration, audio_path)


def _listen_match_count(aligned: list[dict]) -> int:
    return sum(1 for a in aligned if str(a.get("method", "")).startswith("listen"))


def _listen_mean_score(aligned: list[dict]) -> float:
    """직접 매칭 큐의 평균 유사도 — 0.3대 점수는 '비슷한 단어에 간신히 매칭'이므로
    1.0 매칭과 구별해야 한다 (트랙9 사례: weak 0.3~0.5 연쇄로 전체가 밀림)."""
    scores = [
        float(a.get("score") or 0.0)
        for a in aligned
        if str(a.get("method", "")).startswith("listen")
    ]
    return (sum(scores) / len(scores)) if scores else 0.0


def _align_defect_stats(aligned: list[dict]) -> dict[str, int | float]:
    """겹침·과도한 길이·시작시각 뭉침 — 전곡 균등배치 말고 '직접 매칭 실패' 징후."""
    if not aligned:
        return {"ovlp": 0, "long": 0, "pile": 0, "mean_dur": 0.0}
    ovlp = 0
    long = 0
    for i, a in enumerate(aligned):
        dur = float(a["end"]) - float(a["start"])
        if dur > 10.0:
            long += 1
        if i + 1 < len(aligned) and float(a["end"]) > float(aligned[i + 1]["start"]) + 0.15:
            ovlp += 1
    pile = 0
    for a in aligned:
        near = sum(1 for b in aligned if abs(float(b["start"]) - float(a["start"])) < 2.0)
        pile = max(pile, near)
    durs = [float(a["end"]) - float(a["start"]) for a in aligned]
    return {
        "ovlp": ovlp,
        "long": long,
        "pile": pile,
        "mean_dur": sum(durs) / len(durs),
    }


def _align_preference_score(aligned: list[dict]) -> float:
    """매칭 수·평균 유사도는 가산, 겹침·긴큐·뭉침은 감점 — 노래↔가사 직접 매칭 품질."""
    n = max(1, len(aligned))
    matched = _listen_match_count(aligned)
    d = _align_defect_stats(aligned)
    score = matched / n
    # 직접 매칭의 질(평균 유사도): 1.0에 가까울수록 가산, 0.5 미만이면 감점
    ms = _listen_mean_score(aligned)
    if matched:
        score += 0.20 * (ms - 0.5)
    score -= 0.08 * float(d["ovlp"])
    score -= 0.06 * float(d["long"])
    if int(d["pile"]) >= 4:
        score -= 0.25 * (int(d["pile"]) - 3)
    if float(d["mean_dur"]) > 7.0:
        score -= 0.15
    return score


def listen_align_track(whisper_model, audio_path: str, lines: list[str], track_duration: float) -> list[dict]:
    print(f"    🎧 listen-align: {audio_path.split('/')[-1]} ({len(lines)} lines)")
    prompt = " ".join(lines[:8]) if lines else None
    words = extract_whisper_words(whisper_model, audio_path, initial_prompt=prompt)
    print(f"       whisper words={len(words)}")
    seq = align_lines_to_words(lines, words, track_duration, audio_path)
    glob = align_lines_to_words_global(lines, words, track_duration, audio_path)

    def _too_broken(aligned: list[dict]) -> bool:
        d = _align_defect_stats(aligned)
        return int(d["ovlp"]) >= 3 or int(d["pile"]) >= 5 or int(d["long"]) >= 4

    seq_s = _align_preference_score(seq)
    glob_s = _align_preference_score(glob)
    seq_bad = _too_broken(seq)
    glob_bad = _too_broken(glob)

    if seq_bad and not glob_bad:
        aligned, which = glob, "global"
    elif glob_bad and not seq_bad:
        aligned, which = seq, "seq"
    elif seq_bad and glob_bad:
        aligned, which = seq, "seq(forced)"
    elif glob_s > seq_s + 0.05:
        aligned, which = glob, "global"
    else:
        aligned, which = seq, "seq"

    d = _align_defect_stats(aligned)
    print(
        f"       matched={_listen_match_count(aligned)}/{len(aligned)} via={which} "
        f"(seq={seq_s:.2f} glob={glob_s:.2f} ovlp={d['ovlp']} long={d['long']} pile={d['pile']})"
    )
    # 중앙 관문: 어느 쪽을 선택했든 최종 보증
    return sanitize_cue_timeline(aligned, track_duration)


def listen_quality_ok(aligned: list[dict], track_duration: float) -> bool:
    if not aligned or len(aligned) < 2:
        return bool(aligned)
    starts = [float(a["start"]) for a in aligned]
    ends = [float(a["end"]) for a in aligned]
    span = max(ends) - min(starts)
    if span < max(20.0, track_duration * 0.25):
        return False
    # 에너지 폴백 결과는 '직접 매칭'이 아니지만, SSOT(sanitize)를 통과한
    # 결정적 결과이므로 캐시 재사용을 허용한다 (Whisper 실패 트랙이
    # 인코딩마다 재전사되는 낭비 방지).
    methods = {str(a.get("method", "")) for a in aligned}
    if all(m.startswith("energy") for m in methods):
        d = _align_defect_stats(aligned)
        if int(d["ovlp"]) >= 4 or int(d["pile"]) >= 5 or int(d["long"]) >= 4:
            return False
        return True
    listen_n = _listen_match_count(aligned)
    if listen_n < max(2, int(len(aligned) * 0.45)):
        return False
    # end<=start 역전이 하나라도 있으면 무조건 실패
    # (이런 정렬은 자막 겹침·소멸을 일으키므로 캐시 재사용 금지)
    if any(e <= s for s, e in zip(starts, ends)):
        return False
    # 트랙 길이 초과 큐도 실패
    if any(s > track_duration - 0.3 for s in starts):
        return False
    d = _align_defect_stats(aligned)
    if int(d["ovlp"]) >= 4 or int(d["pile"]) >= 5 or int(d["long"]) >= 4:
        return False
    return True