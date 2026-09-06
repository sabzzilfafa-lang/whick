"""오디오 스펙트럼 EQ 막대 — WHICK playlist/daily-music-share make_eq_video 이식."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

EQ_STYLES = ("bars", "thin", "thick", "spaced", "line", "mirror", "dots")

STYLE_BARS = {
    "bars": 32,
    "thin": 32,
    "thick": 20,
    "spaced": 28,
    "line": 32,
    "mirror": 28,
    "dots": 28,
}

# 슬롯 대비 빈 비율. 넓혀도 막대가 붙지 않게.
STYLE_GAP = {
    "bars": 0.32,
    "thin": 0.294,
    "thick": 0.30,
    "spaced": 0.42,
    "mirror": 0.28,
}


def _bar_lr(i: int, n: int, width: int, gap_ratio: float) -> tuple[int, int]:
    """슬롯 안에서 비례 간격. 최소 1px 틈."""
    x0 = i * width / n
    x1 = (i + 1) * width / n
    slot = max(1.0, x1 - x0)
    g = max(0.5, slot * gap_ratio * 0.5)
    left = int(round(x0 + g))
    right = int(round(x1 - g)) - 1
    if right < left:
        left = int(round(x0))
        right = max(left, int(round(x1)) - 1)
    return left, right


def _parse_color(color: str | None) -> tuple[int, int, int, int]:
    """#RGB / #RRGGBB / #RRGGBBAA → RGBA."""
    raw = (color or "#FFFFFF").strip()
    if not raw.startswith("#"):
        raw = f"#{raw}"
    h = raw[1:]
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 6:
        h += "FF"
    if not re.fullmatch(r"[0-9A-Fa-f]{8}", h):
        return (255, 255, 255, 255)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))


def _draw_frame(
    draw,
    vals,
    *,
    style: str,
    width: int,
    height: int,
    n_bars: int,
    fill: tuple[int, int, int, int],
) -> None:
    n = min(n_bars, len(vals))
    if n <= 0:
        return

    def slot(i: int) -> tuple[int, int, int]:
        """전체 너비를 균등 분할 — 오른쪽 여백으로 왼쪽으로 치우치지 않게."""
        x0 = int(round(i * width / n))
        x1 = int(round((i + 1) * width / n))
        cx = (x0 + x1) // 2
        return x0, max(x0 + 1, x1), cx

    if style == "line":
        pts = []
        for i in range(n):
            _, _, cx = slot(i)
            y = int(height - 3 - vals[i] * (height - 8))
            pts.append((cx, y))
        if len(pts) >= 2:
            draw.line(pts, fill=fill, width=max(3, height // 28))
        return

    if style == "mirror":
        mid = height // 2
        for i in range(n):
            left, right = _bar_lr(i, n, width, STYLE_GAP["mirror"])
            bh_px = max(2, int(vals[i] * (mid - 3)))
            draw.rectangle([left, mid - bh_px, right, mid + bh_px], fill=fill)
        return

    if style == "dots":
        for i in range(n):
            x0, x1, cx = slot(i)
            r = max(2, min((x1 - x0) // 3, height // 4))
            cy = int(height - r - 2 - vals[i] * (height - r * 2 - 6))
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
        return

    gap_ratio = STYLE_GAP.get(style, 0.32)
    for i in range(n):
        left, right = _bar_lr(i, n, width, gap_ratio)
        bh_px = int(vals[i] * (height - 4))
        if bh_px < 2:
            bh_px = 2
        bar_w = max(1, right - left)
        radius = 1 if style == "thin" else max(min(bar_w // 2, 6), 2)
        draw.rounded_rectangle(
            [left, height - bh_px, right, height],
            radius=radius,
            fill=fill,
        )


def _band_levels(spec, freqs, n_bars):
    """로그 밴드 에너지. 빈이 없는 칸은 가장 가까운 FFT 빈을 씀."""
    import numpy as np

    bands = np.logspace(np.log10(30), np.log10(16000), n_bars + 1)
    bh = np.zeros(n_bars, dtype=np.float64)
    for i in range(n_bars):
        mask = (freqs >= bands[i]) & (freqs < bands[i + 1])
        if mask.any():
            bh[i] = float(np.max(spec[mask]))
            continue
        center = float(np.sqrt(bands[i] * bands[i + 1]))
        j = int(np.argmin(np.abs(freqs - center)))
        bh[i] = float(spec[j])
    return bh


def make_eq_video(
    audio_path: Path,
    out_video: Path,
    *,
    n_bars: int | None = None,
    fps: float = 21.5,
    width: int = 1000,
    height: int = 80,
    volume_db: float = 20,
    style: str = "bars",
    max_duration: float | None = None,
    color: str | None = "#FFFFFF",
) -> bool:
    """
    투명 배경 EQ 막대 영상(.mov qtrle) 생성.
    실패 시 False (numpy/Pillow/ffmpeg 문제).
    """
    try:
        import numpy as np
        from PIL import Image as PILImage
        from PIL import ImageDraw as PILDraw
    except ImportError:
        return False

    style = style if style in EQ_STYLES else "bars"
    n_bars = int(n_bars or STYLE_BARS[style])
    width = max(8, int(width))
    height = max(8, int(height))
    fill = _parse_color(color)

    out_video.parent.mkdir(parents=True, exist_ok=True)
    pcm = out_video.with_suffix(".pcm")
    sr = 44100
    try:
        extract = [
            "ffmpeg",
            "-y",
            "-i",
            str(audio_path),
        ]
        if max_duration is not None and max_duration > 0:
            extract.extend(["-t", str(max_duration)])
        extract.extend(
            [
                "-af",
                f"volume={volume_db}dB",
                "-ac",
                "1",
                "-ar",
                str(sr),
                "-f",
                "f32le",
                str(pcm),
            ]
        )
        r = subprocess.run(
            extract,
            capture_output=True,
            text=True,
            timeout=600,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0 or not pcm.exists():
            return False

        data = np.fromfile(pcm, dtype=np.float32)
        if len(data) / sr < 1:
            return False

        fft_size = 8192
        hop = max(int(sr / fps), 1)
        freqs = np.fft.rfftfreq(fft_size, 1 / sr)
        frames: list[list[float]] = []
        for start in range(0, len(data) - fft_size, hop):
            window = np.hanning(fft_size) * data[start : start + fft_size]
            spec = np.abs(np.fft.rfft(window))
            frames.append(_band_levels(spec, freqs, n_bars).tolist())

        arr = np.array(frames, dtype=np.float64)
        if len(arr) < 2:
            return False

        log_arr = np.log10(arr + 1e-6)
        ref = np.percentile(log_arr, 99)
        norm = np.clip((log_arr - (ref - 4.0)) / 4.0, 0, 1)
        smooth = norm.copy()
        # attack/decay: 올라갈 땐 즉시 반응, 내려갈 땐 부드럽게 (스펙트럼 민감도 개선)
        attack = 0.96
        decay = 0.30
        for i in range(1, len(smooth)):
            prev = smooth[i - 1]
            cur = norm[i]
            a = np.where(cur > prev, attack, decay)
            smooth[i] = a * cur + (1 - a) * prev

        # PNG+RGBA: qtrle는 윈도우에서 알파가 빠져 투명 영역이 검정으로 붙음
        out_video = out_video.with_suffix(".mov")
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgba",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "pipe:",
            "-an",
            "-c:v",
            "png",
            "-pix_fmt",
            "rgba",
            str(out_video),
        ]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        assert proc.stdin is not None
        for fi in range(len(smooth)):
            img = PILImage.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = PILDraw.Draw(img)
            _draw_frame(
                draw,
                smooth[fi],
                style=style,
                width=width,
                height=height,
                n_bars=n_bars,
                fill=fill,
            )
            proc.stdin.write(img.tobytes("raw", "RGBA"))
        proc.stdin.close()
        proc.wait(timeout=600)
        return proc.returncode == 0 and out_video.exists() and out_video.stat().st_size > 0
    except Exception:
        return False
    finally:
        try:
            if pcm.exists():
                pcm.unlink()
        except OSError:
            pass
