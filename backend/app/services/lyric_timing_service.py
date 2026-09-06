"""가사 타이밍 — Whisper listen-align (균등 배분 금지)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from app.services.listen_align import (
    filter_sung_lines,
    listen_align_track,
    listen_quality_ok,
    sanitize_cue_timeline,
)

logger = logging.getLogger(__name__)

_WHISPER_MODEL = None
_WHISPER_LOAD_TRIED = False


def _lyric_lines(text: str | None) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or re.match(r"^\[.*\]$", s):
            continue
        out.append(s)
    return out


def _is_sung_korean_line(line: str) -> bool:
    s = (line or "").strip()
    if len(s) < 2:
        return False
    hangul = len(re.findall(r"[가-힣]", s))
    if hangul < 2:
        return False
    low = s.lower()
    if low in ("story", "lyrics", "가사", "chorus", "verse", "bridge", "outro", "intro"):
        return False
    if "bpm" in low:
        return False
    return True


def prepare_sung_lines(
    lyrics_en: str | None,
    lyrics_ko: str | None,
) -> tuple[list[str], list[str], str]:
    """정렬용 가창 줄 + KO 페어. 반환: (align_lines, ko_lines, language)."""
    en = _lyric_lines(lyrics_en)
    ko = _lyric_lines(lyrics_ko)

    en_sung, ko_paired = filter_sung_lines(en, ko)
    if en_sung:
        return en_sung, ko_paired, "en"

    # 영문 가창 없으면 한글 가사로 정렬
    ko_sung = [ln for ln in ko if _is_sung_korean_line(ln)]
    if ko_sung:
        return ko_sung, ko_sung, "ko"

    # 최후: 섹션 헤더만 뺀 원문
    primary = en or ko
    return primary, (ko if primary is en else primary), ("en" if en else "ko")


def get_whisper_model(*, size: str = "small"):
    """faster-whisper 모델. 기본 small(정확도 우선). 없으면 None."""
    global _WHISPER_MODEL, _WHISPER_LOAD_TRIED
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    if _WHISPER_LOAD_TRIED:
        return None
    _WHISPER_LOAD_TRIED = True
    try:
        from faster_whisper import WhisperModel

        # small → base → tiny 순으로 시도 (정확도 우선)
        for model_size in (size, "base", "tiny"):
            # CUDA 드라이버 버전 불일치가 흔함(로드는 성공, transcribe 시 실패) →
            # 실제 1초짜리 전사 테스트를 통과한 조합만 사용.
            for device, ctype in (("cuda", "float16"), ("cpu", "int8")):
                try:
                    m = WhisperModel(model_size, device=device, compute_type=ctype)
                    segs, _ = m.transcribe(
                        _make_probe_tone(), language="en", word_timestamps=True
                    )
                    _ = [s.text for s in segs]
                    _WHISPER_MODEL = m
                    logger.info(
                        "Whisper ready: size=%s device=%s compute=%s",
                        model_size,
                        device,
                        ctype,
                    )
                    return _WHISPER_MODEL
                except Exception as e:
                    logger.warning("Whisper %s/%s fail: %s", model_size, device, e)
        return None
    except ImportError:
        logger.warning("faster-whisper 미설치 — pip install faster-whisper")
        return None


def _make_probe_tone() -> str:
    """Whisper 실동작 테스트용 1초 사인 톤 wav."""
    import io
    import wave

    import numpy as np

    buf = io.BytesIO()
    t = np.linspace(0.0, 1.0, 16000, endpoint=False)
    tone = (np.sin(2 * np.pi * 440.0 * t) * 8000).astype(np.int16)
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(tone.tobytes())
    path = Path(tempfile.gettempdir()) / "whisper_probe.wav"
    path.write_bytes(buf.getvalue())
    return str(path)


# 정렬 알고리즘 버전 — 바뀌면 기존 캐시 전부 무효화.
# v2: SSOT 중앙 관문 도입 / v3: 전사 환각 루프 수정(condition_off) + 매칭 시간 상한
_ALIGN_VERSION = "v3"


def _cache_key(audio_path: Path, lines: list[str], *, source_path: Path | None = None) -> str:
    h = hashlib.sha1()
    key_path = Path(source_path or audio_path)
    h.update(_ALIGN_VERSION.encode())
    h.update(str(key_path.resolve()).encode("utf-8", errors="ignore"))
    try:
        st = key_path.stat()
        h.update(str(st.st_mtime_ns).encode())
        h.update(str(st.st_size).encode())
    except OSError:
        pass
    h.update("\n".join(lines).encode("utf-8", errors="ignore"))
    return h.hexdigest()[:16]


def _load_cache(cache_path: Path, key: str, duration: float) -> list[dict] | None:
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if data.get("key") != key:
            return None
        aligned = data.get("aligned") or []
        if not listen_quality_ok(aligned, duration):
            return None
        # 중앙 관문: 과거 버전으로 저장된 캐시라도 로드 시점에 보증
        return sanitize_cue_timeline(aligned, duration)
    except Exception:
        return None


def _save_cache(cache_path: Path, key: str, aligned: list[dict]) -> None:
    try:
        cache_path.write_text(
            json.dumps({"key": key, "aligned": aligned}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def align_track_lyrics(
    audio_path: Path,
    lyrics_en: str | None,
    lyrics_ko: str | None,
    duration_sec: float,
    *,
    cache_dir: Path | None = None,
    cache_source: Path | None = None,
    whisper_model=None,
) -> list[dict[str, Any]]:
    """
    한 곡: [{start, end, en, ko, method}, ...] — 트랙 상대 시간.
    Whisper로 실제 가창 구간에 맞춤. 균등 전곡 배분 안 함.
    """
    lines, ko_lines, lang = prepare_sung_lines(lyrics_en, lyrics_ko)
    if not lines:
        return []

    cache_dir = cache_dir or audio_path.parent
    cache_path = cache_dir / "lyrics_timing.json"
    key = _cache_key(audio_path, lines, source_path=cache_source or audio_path)
    cached = _load_cache(cache_path, key, duration_sec)
    if cached:
        return _pair_ko(cached, ko_lines)

    model = whisper_model if whisper_model is not None else get_whisper_model()
    if model is None:
        logger.warning("Whisper 없음 — 에너지 기반 보컬 추정 구간 사용")
        return _energy_window_cues(lines, ko_lines, duration_sec, str(audio_path))

    if lang == "ko":
        aligned = _listen_align_korean(model, str(audio_path), lines, duration_sec, ko_lines)
    else:
        aligned = listen_align_track(model, str(audio_path), lines, duration_sec)

    if not aligned:
        return _energy_window_cues(lines, ko_lines, duration_sec, str(audio_path))

    # 중앙 관문: 한국어 세그먼트 정렬은 listen_align_track을 우회하므로
    # 여기서 반드시 SSOT 검사를 통과시킨다 (역전/초과/겹침 절대 방지)
    aligned = sanitize_cue_timeline(aligned, duration_sec)

    # sanitize로 큐가 일부 제거돼도 한/영 짝이 어긋나지 않게:
    # 큐 텍스트(en)를 원래 가사 줄 역매핑해 그 줄의 한글을 직접 붙인다.
    line_to_ko = {line: (ko_lines[i] if i < len(ko_lines) else "") for i, line in enumerate(lines)}
    for a in aligned:
        txt = a.get("text") or a.get("en") or ""
        if txt and txt in line_to_ko:
            a["_ko"] = line_to_ko[txt]

    _save_cache(cache_path, key, aligned)
    return _pair_ko(aligned, ko_lines)


def _pair_ko(aligned: list[dict], ko_lines: list[str]) -> list[dict[str, Any]]:
    """정렬 결과에 한글 가사를 짝지어 붙인다.

    큐(dict)에 이미 '_ko'가 부착돼 있으면(정렬 전 1:1 부착) 그 값을 쓴다.
    sanitize_cue_timeline이 큐를 제거해도 인덱스가 어긋나지 않도록 하기 위함.
    """
    out: list[dict[str, Any]] = []
    for i, a in enumerate(aligned):
        ko = a.get("_ko")
        if ko is None:
            ko = ko_lines[i] if i < len(ko_lines) else ""
        out.append(
            {
                "start": float(a["start"]),
                "end": float(a["end"]),
                "en": a.get("text") or "",
                "ko": ko or "",
                "method": a.get("method", ""),
            }
        )
    return out


def _energy_window_cues(
    lines: list[str],
    ko_lines: list[str],
    duration_sec: float,
    audio_path: str | None = None,
) -> list[dict[str, Any]]:
    """Whisper 완전 실패 시: librosa RMS 에너지 기반 보컬 구간 추정.

    실제 오디오의 에너지 프로파일에서 조용한 구간(인트로/아웃트로/간주)을
    제외한 '소리 나는 구간' 안에만 가사를 배치한다. 에너지 분석 실패 시
    전곡의 15%~92%를 추정 보컬 구간으로 사용.
    """
    try:
        import librosa
        import numpy as np
    except ImportError:
        librosa = None

    # 보컬 추정 구간 (에너지 분석 성공 시 실측으로 대체)
    v0 = min(20.0, duration_sec * 0.15)
    v1 = max(v0 + 25.0, duration_sec - 5.0)

    if librosa is not None and audio_path and duration_sec > 5:
        try:
            y, sr = librosa.core.load(str(audio_path), sr=22050, mono=True)
            hop = 512
            rms = librosa.feature.rms(y=y, hop_length=hop)[0]
            times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop)
            thr = float(np.max(rms)) * 0.12
            loud = times[rms > thr]
            if len(loud) > 0:
                # 첫/마지막 '소리 나는' 시점 = 보컬+반주 활동 구간
                v0 = float(max(0.0, loud[0] - 1.0))
                v1 = float(min(duration_sec - 0.5, loud[-1] + 1.0))
        except Exception:
            pass  # 기본 v0/v1 유지

    v0 = max(0.0, min(v0, duration_sec - 10.0))
    v1 = max(v0 + 15.0, min(v1, duration_sec - 0.5))

    step = max(2.5, (v1 - v0) / max(1, len(lines)))
    out = []
    for i, line in enumerate(lines):
        st = v0 + i * step
        en = min(duration_sec - 0.4, st + min(step * 0.88, 5.0))
        out.append(
            {
                "start": round(st, 2),
                "end": round(en, 2),
                "en": line,
                "ko": ko_lines[i] if i < len(ko_lines) else "",
                "method": "energy_window",
            }
        )
    return out


def _listen_align_korean(whisper_model, audio_path: str, lines: list[str], track_duration: float, ko_lines: list[str] | None = None):
    """한글 가사 트랙 정렬.

    중요: 한국어 가사 트랙도 실제 노래는 영어인 경우가 많다 (Suno 영어 작곡 + 한국어 가사 표기).
    language='ko' 강제 + vad_filter=True 조합은 이 경우 실제 영어 가창을 전사하지 못해
    30~90초짜리 무의미 세그먼트만 남는다 (트랙12 사례: 129.5~281s에 2개 세그먼트).
    → 언어 자동감지 + VAD 끔(가창 보존). 결과가 한국어 가창이면 세그먼트 매칭,
      영어 가창이면 단어 정렬 경로를 탄다.
    """
    from app.services.listen_align import align_lines_to_words

    ko_lines = ko_lines or []

    segments, info = whisper_model.transcribe(
        audio_path,
        language=None,  # 자동 감지 — 한국어 가창/영어 가창 모두 커버
        beam_size=5,
        vad_filter=False,  # VAD는 가창 보컬을 비음성으로 잘라버림 (영문 경로와 동일)
        word_timestamps=True,
    )

    lang = (getattr(info, "language", None) or "").lower()
    words: list[dict[str, Any]] = []
    seg_list = []
    ko_hangul_in_words = 0
    for seg in segments:
        seg_list.append(seg)
        if seg.words:
            for w in seg.words:
                tok = (w.word or "").strip()
                if tok:
                    if re.search(r"[가-힣]", tok):
                        ko_hangul_in_words += 1
                    words.append({"start": float(w.start), "end": float(w.end), "word": tok})
        else:
            tok = (seg.text or "").strip()
            if tok:
                words.append({"start": float(seg.start), "end": float(seg.end), "word": tok})

    # 실질 언어 판정: 단어의 한글 비중. Whisper 자동감지는 노래(반주 섞인 보컬)에서
    # 신뢰도가 낮아 여기선 보조 근거로만 사용. 한글이 30% 미만이면 영어 가창으로 보고
    # 영문 단어 정렬 경로를 탄다 (한국어 가사 + 영어 보컬 트랙 커버).
    ko_ratio = (ko_hangul_in_words / len(words)) if words else 0.0
    is_korean_sung = ko_ratio >= 0.3 or (ko_ratio >= 0.1 and lang.startswith("ko"))

    # 참고: 한국어 가사(lines)는 norm_tok()에서 한글이 제거되어 영문 단어 매처
    # (align_lines_to_words)로는 원천적으로 매칭 불가다. 따라서 한국어 가창이 아닌
    # 것으로 판정되면 단어 정렬을 시도하지 말고 세그먼트 구조 배치로 간다.

    # === 한국어 가창이 아닌 것으로 판정된 경우 ===
    # 1차 자동감지(en) 전사의 세그먼트는 실제 가창 구조(개수·시간분포)를 정확히
    # 반영한다. 노래는 영어인데 가사 파일만 한국어인 트랙은 세그먼트와 가사 줄이
    # 거의 1:1로 대응되므(트랙12 실측: 세그먼트 47↔줄 46, 순서 완전 일치),
    # 세그먼트 시간 구조에 줄을 순서대로 배치한다.
    # (한국어 가사는 norm_tok()에서 한글이 제거되어 영문 단어 매처로는 원천 매칭
    #  불가 → 이 구조 배치가 최선. 텍스트 환각과 무관하게 '위치'는 정확하다.)
    if not is_korean_sung and seg_list:
        return _place_lines_on_segments(lines, ko_lines, seg_list, track_duration, audio_path)

    if is_korean_sung and seg_list:
        # 환각 반복 감지: 세그먼트 텍스트가 거의 같은 문장 반복이면 Whisper 실패
        # (과거 트랙12 사례: 세그먼트 전부 "노래가 참 쓸쓸하구나" 반복)
        def norm_seg(s: str) -> str:
            return re.sub(r"[^가-힣a-z0-9]", "", (s or "").lower())

        texts = [norm_seg(seg.text or "") for seg in seg_list if (seg.text or "").strip()]
        if texts:
            distinct = len(set(texts))
            variety = distinct / len(texts)
            if variety < 0.5:
                logger.warning(
                    "Whisper 한국어 환각 반복 감지 (다양성 %.2f) — 에너지 폴백 전환",
                    variety,
                )
                return _energy_window_cues(
                    lines, ko_lines, track_duration, audio_path
                )
        return _align_korean_segments(lines, seg_list, track_duration)

    return _energy_window_cues(lines, ko_lines, track_duration, audio_path)


def _place_lines_on_segments(
    lines: list[str],
    ko_lines: list[str],
    seg_list: list[Any],
    track_duration: float,
    audio_path: str | None = None,
) -> list[dict[str, Any]]:
    """가창 세그먼트 시간 구조에 가사 줄을 순서대로 1:1 배치.

    세그먼트 수 >= 줄 수: 줄 위치에 비례 매핑(앞 세그먼트 우선).
    세그먼트 수 < 줄 수: 세그먼트 전 구간을 줄 수로 균등 분할.
    결과는 sanitize_cue_timeline의 중앙 관문을 통과한다.
    """
    spans: list[tuple[float, float]] = [
        (float(s.start), float(s.end)) for s in seg_list
    ]
    n = len(lines)
    if not spans or n == 0:
        return _energy_window_cues(lines, ko_lines, track_duration, audio_path)

    if len(spans) >= n:
        picked: list[tuple[float, float]] = []
        last_i = -1
        for i in range(n):
            idx = min(round(i * len(spans) / n), len(spans) - 1)
            if idx <= last_i:
                idx = min(last_i + 1, len(spans) - 1)
            picked.append(spans[idx])
            last_i = idx
    else:
        t0 = spans[0][0]
        t1 = spans[-1][1]
        step = max(2.5, (t1 - t0) / n)
        picked = [(t0 + i * step, t0 + (i + 1) * step) for i in range(n)]

    aligned: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        st, en = picked[i]
        if en - st < 2.0:
            en = st + 3.0
        aligned.append(
            {
                "start": round(max(0.0, st), 2),
                "end": round(en, 2),
                "text": line,
                "score": 0.0,
                "method": "listen_ko_seg",
            }
        )
    # 중앙 관문: 겹침/역전/초과 일괄 해소
    from app.services.listen_align import sanitize_cue_timeline

    return sanitize_cue_timeline(aligned, track_duration)


def _align_korean_segments(lines: list[str], seg_list, track_duration: float) -> list[dict]:
    from difflib import SequenceMatcher

    def norm_ko(s: str) -> str:
        return re.sub(r"[^가-힣a-z0-9]", "", (s or "").lower())

    if not seg_list:
        return []

    aligned = []
    cur = 0
    n = len(seg_list)

    # 멀티 세그먼트 컨텍스트: 여러 seg를 합쳐서 매칭 정확도 향상
    def seg_context(j: int, width: int = 1) -> str:
        """j 주변의 세그먼트를 합쳐 더 넓은 컨텍스트로 매칭."""
        texts = []
        for k in range(max(0, j - width), min(n, j + width + 1)):
            texts.append(seg_list[k].text or "")
        return " ".join(texts)

    for i, line in enumerate(lines):
        target = norm_ko(line)
        best_j, best_score = -1, -1.0
        search_end = min(n, cur + max(6, int(n / max(1, len(lines) - i) * 4) + 3))
        for j in range(cur, search_end):
            context = seg_context(j, width=1)
            score = SequenceMatcher(None, target, norm_ko(context)).ratio()
            if score > best_score:
                best_score = score
                best_j = j
        if best_score >= 0.25 and best_j >= 0:
            st = float(seg_list[best_j].start)
            en = float(seg_list[best_j].end)
            cur = best_j + 1
            method = "listen_ko"
        elif cur < n:
            st = float(seg_list[cur].start)
            en = float(seg_list[cur].end)
            cur = min(n - 1, cur + 1)
            method = "listen_ko_weak"
        else:
            st = float(seg_list[-1].end) + i * 0.3
            en = st + 3.0
            method = "interp"
        if en - st < 1.8:
            en = min(track_duration - 0.4, st + 3.0)
        # weak/interp 큐도 항상 앞 큐보다 뒤에 배치 (곡 끝에 몰리면
        # 수십 줄이 같은 시각에 겹쳐 자막이 뭉개짐 → 균등 간격으로 전진 보장)
        if aligned:
            prev = aligned[-1]
            min_gap = 1.9
            min_start = float(prev["start"]) + min_gap
            if float(st) < min_start:
                st = min_start
                en = max(float(en), st + 1.9)
        aligned.append(
            {
                "start": round(max(0.0, min(float(st), track_duration - 1.6)), 2),
                "end": round(min(track_duration - 0.2, float(en)), 2),
                "text": line,
                "score": round(best_score, 3),
                "method": method,
            }
        )

    max_start = max(0.0, track_duration - 2.0)
    for pass_ in range(2):
        for k in range(1, len(aligned)):
            # 시작 간격 보장: 이전 시작 + 0.9s (끝 몰림 방지 — 46줄이 313s에
            # 들어가려면 최소 0.9s 간격 필요. 0.25s 간격은 10줄 겹침 유발)
            if aligned[k]["start"] < aligned[k - 1]["start"] + 0.9:
                aligned[k]["start"] = round(
                    min(max_start, aligned[k - 1]["start"] + 0.95), 2
                )
            if aligned[k]["start"] <= aligned[k - 1]["end"]:
                aligned[k - 1]["end"] = round(
                    max(aligned[k - 1]["start"] + 1.8, aligned[k]["start"] - 0.1), 2
                )
    # 최종 보증은 상위(align_track_lyrics)의 중앙 관문(sanitize_cue_timeline)이 담당
    return aligned


def build_album_cues(
    tracks: list[dict[str, Any]],
    *,
    whisper_model=None,
) -> list[dict[str, Any]]:
    """
    tracks: start/end/duration/audio_path/lyrics_en/lyrics_ko/title/project
    → 절대 타임라인 cues [{start,end,en,ko,track}]
    """
    model = whisper_model if whisper_model is not None else get_whisper_model()
    cues: list[dict[str, Any]] = []
    for t in tracks:
        audio = t.get("audio_path")
        if not audio:
            continue
        audio_path = Path(audio)
        dur = float(t.get("duration") or (float(t["end"]) - float(t["start"])))
        project = Path(t["project"]) if t.get("project") else audio_path.parent
        source = Path(t["source_audio"]) if t.get("source_audio") else None
        timed = align_track_lyrics(
            audio_path,
            t.get("lyrics_en"),
            t.get("lyrics_ko"),
            dur,
            cache_dir=project,
            cache_source=source,
            whisper_model=model,
        )
        offset = float(t["start"])
        track_dur = float(t.get("duration") or (float(t["end"]) - float(t["start"])))
        # 중앙 관문 (SSOT): align_track_lyrics 내부에서 이미 통과하지만,
        # 앨범 합산 시각에서도 동일 보증을 위해 트랙 상대시간으로 재검사.
        # 과거 버전 캐시가 오더라도 여기서 역전/초과/겹침이 절대 제거됨.
        timed = sanitize_cue_timeline(timed, track_dur)
        for c in timed:
            cues.append(
                {
                    "start": round(offset + float(c["start"]), 2),
                    "end": round(offset + float(c["end"]), 2),
                    "en": c.get("en") or "",
                    "ko": c.get("ko") or "",
                    "track": t.get("title") or "",
                    "method": c.get("method") or "",
                }
            )
    return cues