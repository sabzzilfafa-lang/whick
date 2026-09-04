#!/usr/bin/env python3
"""8초 로그 스윕 WAV (40–500Hz) — 룸보정 재생용."""
import math
import struct
import wave
from pathlib import Path

SR = 48000
DURATION = 8.0
F_MIN, F_MAX = 40.0, 500.0
GAIN = 0.35


def integrated_phase_rad(t: float) -> float:
    """Log sweep phase: f(t)=f0*(f1/f0)^(t/T) → ∫f dt."""
    if t <= 0:
        return 0.0
    ratio = F_MAX / F_MIN
    return 2 * math.pi * F_MIN * DURATION / math.log(ratio) * (ratio ** (t / DURATION) - 1)


def main() -> None:
    out = Path(__file__).resolve().parent / "log-sweep.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    n = int(SR * DURATION)
    with wave.open(str(out), "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        for i in range(n):
            t = i / SR
            sample = GAIN * math.sin(integrated_phase_rad(t))
            packed = struct.pack("<h", int(max(-32767, min(32767, sample * 32767))))
            wf.writeframes(packed + packed)
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
