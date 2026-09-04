"""MPD fifo PCM → log-spaced bands → WebSocket (미니PC SSOT)."""
from __future__ import annotations

import asyncio
import math
import os
import struct
from typing import Awaitable, Callable

BAND_COUNT = int(os.getenv("WHICK_SPECTRUM_BANDS", "24"))
SAMPLE_RATE = int(os.getenv("WHICK_SPECTRUM_SAMPLE_RATE", "44100"))
FRAME_SAMPLES = int(os.getenv("WHICK_SPECTRUM_FRAME", "2048"))
EMIT_HZ = float(os.getenv("WHICK_SPECTRUM_HZ", "15"))
ATTACK = float(os.getenv("WHICK_SPECTRUM_ATTACK", "0.55"))
RELEASE = float(os.getenv("WHICK_SPECTRUM_RELEASE", "0.12"))
# Drain process keeps FIFO clear; spectrum reads this regular file (never opens FIFO).
SPECTRUM_RING = os.getenv("WHICK_SPECTRUM_RING", "/var/lib/whick/run/spectrum-ring.pcm")


def log_band_freqs(count: int = BAND_COUNT, fmin: float = 80.0, fmax: float = 12000.0) -> list[float]:
    if count <= 1:
        return [fmin]
    ratio = fmax / fmin
    return [fmin * (ratio ** (i / (count - 1))) for i in range(count)]


def goertzel_mag(samples: list[float], sample_rate: int, freq: float) -> float:
    n = len(samples)
    if n < 8 or freq <= 0:
        return 0.0
    k = int(0.5 + n * freq / sample_rate)
    w = (2.0 * math.pi * k) / n
    coeff = 2.0 * math.cos(w)
    s0 = s1 = s2 = 0.0
    for x in samples:
        s0 = x + coeff * s1 - s2
        s2 = s1
        s1 = s0
    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    return math.sqrt(max(0.0, power)) / n


def pcm_to_mono(pcm: bytes) -> list[float]:
    n = len(pcm) // 4
    if n <= 0:
        return []
    out: list[float] = []
    for i in range(n):
        left, right = struct.unpack_from("<hh", pcm, i * 4)
        out.append((left + right) / 65536.0)
    return out


def analyze_pcm(pcm: bytes, *, prev: list[float]) -> list[float]:
    mono = pcm_to_mono(pcm)
    if len(mono) < FRAME_SAMPLES:
        mono = ([0.0] * (FRAME_SAMPLES - len(mono))) + mono
    window = mono[-FRAME_SAMPLES:]
    freqs = log_band_freqs()
    raw = [goertzel_mag(window, SAMPLE_RATE, f) for f in freqs]
    peak = max(raw) if raw else 0.0
    norm = 1.0 / max(peak, 1e-5)
    out: list[float] = []
    for i, val in enumerate(raw):
        target = min(1.0, max(0.0, val * norm * 1.15))
        prev_val = prev[i] if i < len(prev) else 0.0
        alpha = ATTACK if target > prev_val else RELEASE
        out.append(prev_val + (target - prev_val) * alpha)
    return out


class SpectrumEngine:
    def __init__(
        self,
        fifo_path: str,
        emit: Callable[[list[float], str], Awaitable[None]],
        *,
        is_playing: Callable[[], bool],
        source: Callable[[], str],
    ) -> None:
        self.fifo_path = fifo_path
        self.ring_path = os.getenv("WHICK_SPECTRUM_RING", SPECTRUM_RING)
        self.emit = emit
        self.is_playing = is_playing
        self.source = source
        self._smooth = [0.0] * BAND_COUNT
        self._task: asyncio.Task | None = None
        self._fd: int | None = None

    def _open_fifo(self) -> None:
        """Ring 파일만 연다 — FIFO drain PID를 kill 하지 않음 (재생 끊김 방지)."""
        if self._fd is not None:
            return
        path = self.ring_path if os.path.exists(self.ring_path) else self.fifo_path
        try:
            self._fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except FileNotFoundError:
            self._fd = None

    def _close_fifo(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def _read_latest_frame(self) -> bytes:
        need = FRAME_SAMPLES * 4
        # Prefer fresh ring snapshot (regular file rewritten by drain)
        try:
            with open(self.ring_path, "rb") as f:
                data = f.read()
            if len(data) >= need // 2:
                return data[-need:] if len(data) > need else data
        except OSError:
            pass
        if self._fd is None:
            self._open_fifo()
        if self._fd is None:
            return b""
        buf = b""
        while True:
            try:
                chunk = os.read(self._fd, need * 8)
            except BlockingIOError:
                break
            if not chunk:
                break
            buf = (buf + chunk)[-need:]
        return buf if len(buf) >= need // 2 else b""

    def _analyze_blocking(self) -> list[float]:
        pcm = self._read_latest_frame()
        if not pcm:
            return [max(0.0, v * 0.85) for v in self._smooth]
        self._smooth = analyze_pcm(pcm, prev=self._smooth)
        return list(self._smooth)

    async def _loop(self) -> None:
        interval = 1.0 / max(1.0, EMIT_HZ)
        while True:
            try:
                if self.is_playing():
                    bands = await asyncio.to_thread(self._analyze_blocking)
                    await self.emit(bands, self.source())
                else:
                    if any(v > 0.01 for v in self._smooth):
                        self._smooth = [max(0.0, v * 0.7) for v in self._smooth]
                        await self.emit(list(self._smooth), self.source())
                    self._close_fifo()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[spectrum] loop: {exc}")
                self._close_fifo()
            await asyncio.sleep(interval)

    def start(self) -> asyncio.Task:
        if self._task and not self._task.done():
            return self._task
        self._task = asyncio.create_task(self._loop())
        return self._task

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
        self._close_fifo()
