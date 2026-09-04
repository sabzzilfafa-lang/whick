#!/usr/bin/env python3
"""MPD spectrum FIFO 상시 drain — 재생 끊김 방지용.

MPD가 fifo에 쓰는 PCM을 항상 읽어내어 버퍼가 가득 차 MPD(및 DAC 출력)가
블록되지 않게 한다. 스펙트럼 UI는 ring 파일만 읽는다 (FIFO 단독 reader 경쟁 제거).
"""
from __future__ import annotations

import os
import sys
import time

FIFO = os.environ.get("WHICK_SPECTRUM_FIFO", "/var/lib/whick/run/mpd-spectrum.pcm")
RING = os.environ.get("WHICK_SPECTRUM_RING", "/var/lib/whick/run/spectrum-ring.pcm")
# 48kHz stereo s16le ≈ 192KB/s — keep ~0.5s for analysis
RING_BYTES = int(os.environ.get("WHICK_SPECTRUM_RING_BYTES", str(192_000 // 2)))
READ_CHUNK = 65536


def main() -> int:
    os.makedirs(os.path.dirname(RING) or ".", exist_ok=True)
    # Ensure fifo exists (entrypoint usually creates it)
    if not os.path.exists(FIFO):
        try:
            os.mkfifo(FIFO)
        except FileExistsError:
            pass

    buf = bytearray()
    while True:
        fd = None
        try:
            # Blocking open waits for MPD writer; that's fine for a dedicated drain.
            fd = os.open(FIFO, os.O_RDONLY)
            while True:
                chunk = os.read(fd, READ_CHUNK)
                if not chunk:
                    # Writer closed — reopen after short pause
                    break
                buf.extend(chunk)
                if len(buf) > RING_BYTES * 2:
                    del buf[: len(buf) - RING_BYTES]
                # Atomic-ish replace via temp + rename
                tmp = RING + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(bytes(buf[-RING_BYTES:]))
                os.replace(tmp, RING)
        except FileNotFoundError:
            time.sleep(0.5)
        except OSError as exc:
            print(f"[spectrum-drain] {exc}", file=sys.stderr)
            time.sleep(0.5)
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            time.sleep(0.05)


if __name__ == "__main__":
    raise SystemExit(main())
