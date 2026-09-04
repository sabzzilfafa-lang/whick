#!/usr/bin/env python3
"""FIFO(S32LE) → Camilla Stdin(FLOAT32LE). EOF 후에도 프로세스를 유지해 상주 stdin을 끊지 않음."""
from __future__ import annotations

import array
import os
import sys
import time
from pathlib import Path

FIFO = Path(os.getenv("WHICK_CAMILLA_FIFO", "/var/lib/whick/run/camilla-in.pcm"))
CHUNK = 4096  # bytes of s32le
SILENCE_F32 = (b"\x00" * 8) * 128  # 128 stereo float frames of silence


def s32le_to_f32le(buf: bytes) -> bytes:
    if len(buf) < 4:
        return b""
    n = len(buf) // 4
    samples = array.array("i")
    samples.frombytes(buf[: n * 4])
    if sys.byteorder != "little":
        samples.byteswap()
    out = array.array("f", (s / 2147483648.0 for s in samples))
    return out.tobytes()


def main() -> int:
    FIFO.parent.mkdir(parents=True, exist_ok=True)
    if not FIFO.exists():
        os.mkfifo(FIFO, 0o666)
    out = sys.stdout.buffer
    while True:
        try:
            with open(FIFO, "rb", buffering=0) as fifo:
                while True:
                    data = fifo.read(CHUNK)
                    if not data:
                        break
                    converted = s32le_to_f32le(data)
                    if converted:
                        out.write(converted)
                        out.flush()
        except FileNotFoundError:
            time.sleep(0.2)
            continue
        except Exception as exc:
            sys.stderr.write(f"[camilla-fifo-bridge] {exc}\n")
            time.sleep(0.2)
        # writer closed — keep Camilla stdin alive with short silence
        try:
            out.write(SILENCE_F32)
            out.flush()
        except BrokenPipeError:
            return 1
        time.sleep(0.01)


if __name__ == "__main__":
    raise SystemExit(main())
