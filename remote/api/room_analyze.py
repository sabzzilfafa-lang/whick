"""Room correction analysis — runs on mini-PC (phone uploads mic PCM only)."""
from __future__ import annotations

import base64
import math
import struct
from typing import Any

ROOM_MODE_BANDS = [20, 40, 63, 80, 100, 125, 200, 250, 300]
LEGACY_BANDS = [63, 125, 250, 500]

DEVICE_PROFILES: dict[str, dict[str, Any]] = {
    "generic": {"id": "generic", "label": "일반 스마트폰 (자동)", "band_correction_db": {}},
    "iphone-15": {
        "id": "iphone-15",
        "label": "iPhone 15 계열",
        "band_correction_db": {63: 1.2, 125: 0.8, 200: -0.5, 250: -1},
    },
    "iphone-16": {
        "id": "iphone-16",
        "label": "iPhone 16 계열",
        "band_correction_db": {63: 1.0, 125: 0.6, 200: -0.4, 250: -0.8},
    },
    "galaxy-s24": {
        "id": "galaxy-s24",
        "label": "Galaxy S24 계열",
        "band_correction_db": {40: -1.5, 63: -0.8, 125: 0.5, 200: 1.0},
    },
    "galaxy-s25": {
        "id": "galaxy-s25",
        "label": "Galaxy S25 계열",
        "band_correction_db": {40: -1.2, 63: -0.6, 125: 0.4, 200: 0.8},
    },
}


def decode_samples_b64(samples_b64: str) -> list[float]:
    raw = base64.b64decode(samples_b64)
    n = len(raw) // 4
    if n <= 0:
        return []
    return list(struct.unpack(f"<{n}f", raw[: n * 4]))


def apply_device_profile(band_levels_db: list[dict[str, float]], profile_id: str) -> list[dict[str, float]]:
    profile = DEVICE_PROFILES.get(profile_id) or DEVICE_PROFILES["generic"]
    corrections: dict[int, float] = profile.get("band_correction_db") or {}
    out: list[dict[str, float]] = []
    for b in band_levels_db:
        freq = int(b["freq"])
        out.append({"freq": freq, "db": b["db"] - corrections.get(freq, 0.0)})
    return out


def band_energy(samples: list[float], sample_rate: int, center_hz: float) -> float:
    window_size = 2048
    hop = 1024
    total = 0.0
    count = 0
    omega = (2.0 * math.pi * center_hz) / sample_rate
    for i in range(0, len(samples) - window_size, hop):
        re = 0.0
        im = 0.0
        for j in range(window_size):
            w = 0.5 * (1.0 - math.cos((2.0 * math.pi * j) / (window_size - 1)))
            s = samples[i + j] * w
            re += s * math.cos(omega * j)
            im += s * math.sin(omega * j)
        total += re * re + im * im
        count += 1
    return total / count if count else 0.0


def peaking_from_band_levels(
    band_levels_db: list[dict[str, float]],
    level: str,
    room_only: bool,
) -> list[dict[str, float]]:
    focus = (
        [b for b in band_levels_db if 20 <= b["freq"] <= 300]
        if room_only
        else band_levels_db
    )
    if not focus:
        focus = band_levels_db
    ref = sum(b["db"] for b in focus) / max(len(focus), 1)
    peaking: list[dict[str, float]] = []
    threshold = 2.0 if room_only else 2.5
    for b in focus:
        excess = b["db"] - ref
        if excess > threshold:
            freq = b["freq"]
            q = 1.2 if freq < 100 else 1.4 if freq < 200 else 1.5
            gain = max(-8.0, min(-1.0, -round(excess * 0.55 * 10) / 10))
            peaking.append({"freq": freq, "q": q, "gainDb": gain})
    if not peaking:
        peaking.append({"freq": 80 if room_only else 125, "q": 1.2, "gainDb": -1.5})
    limit = 6 if room_only else 8
    return peaking[:limit]


def analyze_room_recording(
    samples: list[float],
    sample_rate: int,
    level: str = "smartphone",
    *,
    device_profile_id: str | None = None,
    room_mode_only: bool = True,
) -> dict[str, Any]:
    room_only = room_mode_only and level == "smartphone"
    bands = ROOM_MODE_BANDS if room_only else LEGACY_BANDS
    band_levels_db = [
        {"freq": freq, "db": 10.0 * math.log10(band_energy(samples, sample_rate, freq) + 1e-12)}
        for freq in bands
    ]
    if level == "smartphone" and device_profile_id:
        band_levels_db = apply_device_profile(band_levels_db, device_profile_id)
    peaking = peaking_from_band_levels(band_levels_db, level, room_only)
    note = (
        "스마트폰 마이크 · 20~300Hz 룸모드 PEQ"
        if level == "smartphone"
        else "UMIK 측정"
    )
    return {
        "level": level,
        "peaking": peaking,
        "bandLevelsDb": band_levels_db,
        "note": note,
    }


def average_room_measurements(runs: list[dict[str, Any]], *, point_count: int) -> dict[str, Any]:
    if not runs:
        raise ValueError("측정 데이터가 없습니다.")
    freq_set: set[int] = set()
    for run in runs:
        for b in run.get("bandLevelsDb") or run.get("band_levels_db") or []:
            freq_set.add(int(b["freq"]))
    freqs = sorted(freq_set)
    band_levels_db: list[dict[str, float]] = []
    for freq in freqs:
        vals = []
        for run in runs:
            levels = run.get("bandLevelsDb") or run.get("band_levels_db") or []
            hit = next((b for b in levels if int(b["freq"]) == freq), None)
            if hit is not None:
                vals.append(float(hit["db"]))
        avg = sum(vals) / max(len(vals), 1)
        band_levels_db.append({"freq": freq, "db": round(avg * 10) / 10})
    return {
        "level": "smartphone",
        "peaking": peaking_from_band_levels(band_levels_db, "smartphone", True),
        "bandLevelsDb": band_levels_db,
        "note": f"스마트폰 {point_count}포인트 평균 · 20~300Hz 룸모드 PEQ",
    }
