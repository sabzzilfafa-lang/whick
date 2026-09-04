#!/usr/bin/env python3
"""스테레오 L/R 테스트 톤 — 룸보정 스피커 확인용 (440Hz, 1.2s)."""
import math
import struct
import wave
from pathlib import Path

SR = 48000
DURATION = 1.2
FREQ = 440.0
GAIN = 0.45


def write_stereo_tone(path: Path, *, left: bool, right: bool) -> None:
    n = int(SR * DURATION)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        for i in range(n):
            t = i / SR
            env = 1.0
            if t < 0.02:
                env = t / 0.02
            elif t > DURATION - 0.05:
                env = max(0.0, (DURATION - t) / 0.05)
            sample = GAIN * env * math.sin(2 * math.pi * FREQ * t)
            lv = sample if left else 0.0
            rv = sample if right else 0.0
            wf.writeframes(
                struct.pack(
                    "<hh",
                    int(max(-32767, min(32767, lv * 32767))),
                    int(max(-32767, min(32767, rv * 32767))),
                )
            )


def main() -> None:
    out_dir = Path(__file__).resolve().parent
    left = out_dir / "test-left.wav"
    right = out_dir / "test-right.wav"
    write_stereo_tone(left, left=True, right=False)
    write_stereo_tone(right, left=False, right=True)
    print(f"wrote {left} ({left.stat().st_size} bytes)")
    print(f"wrote {right} ({right.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
