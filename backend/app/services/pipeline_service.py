"""로컬 FFmpeg 파이프라인 — 리마스터, 자막, 영상 생성."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from app.services.pipeline_defaults import get_default_config

AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"}


def find_ffmpeg() -> str | None:
    try:
        r = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            return "ffmpeg"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def detect_video_encoder(preferred: str = "auto") -> str:
    if preferred and preferred != "auto":
        return preferred
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return "libx264"
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    encoders = r.stdout or ""
    if "h264_amf" in encoders:
        return "h264_amf"
    if "h264_nvenc" in encoders:
        return "h264_nvenc"
    return "libx264"


def probe_duration(audio_path: Path) -> float:
    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        return 180.0
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 180.0


def _ass_color(white: bool = True) -> str:
    return "&H00FFFFFF" if white else "&H00000000"


def build_ass_content(
    track_title: str,
    lyrics_en: str | None,
    lyrics_ko: str | None,
    duration_sec: float,
    config: dict,
) -> str:
    sub = config.get("subtitle", {})
    track_s = sub.get("track_style", {})
    lyrics_s = sub.get("lyrics_style", {})
    font = sub.get("font_name", "Arial")

    def style_line(name: str, st: dict) -> str:
        return (
            f"Style: {name},{font},{st.get('font_size', 54)},"
            f"&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
            f"0,0,0,0,100,100,0,0,1,{st.get('outline', 3)},"
            f"{st.get('shadow', 1)},{st.get('alignment', 2)},"
            f"{st.get('margin_l', 60)},{st.get('margin_r', 60)},"
            f"{st.get('margin_v', 150)},1"
        )

    lines = [
        "[Script Info]",
        "Title: Suno Helper",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style_line("Track", track_s),
        style_line("Lyrics", lyrics_s),
        style_line("LyricsKo", lyrics_s),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    end = _fmt_time(duration_sec)
    safe_title = track_title.replace("\n", " ")
    lines.append(f"Dialogue: 0,0:00:02.00,{end},Track,,0,0,0,,{safe_title}")

    lyric_text = lyrics_en or lyrics_ko or ""
    lyric_lines = [ln.strip() for ln in lyric_text.splitlines() if ln.strip()]
    if lyric_lines:
        start_offset = 5.0
        available = max(duration_sec - start_offset - 2, 10)
        per_line = available / len(lyric_lines)
        for i, text in enumerate(lyric_lines):
            start = start_offset + i * per_line
            end_t = min(start + per_line, duration_sec)
            style = "Lyrics" if lyrics_en else "LyricsKo"
            if lyrics_en and lyrics_ko and i < len(lyric_lines):
                style = "Lyrics"
            lines.append(
                f"Dialogue: 0,{_fmt_time(start)},{_fmt_time(end_t)},{style},,0,0,0,,{text}"
            )

    if lyrics_ko and lyrics_en:
        ko_lines = [ln.strip() for ln in lyrics_ko.splitlines() if ln.strip()]
        if ko_lines:
            start_offset = 5.5
            available = max(duration_sec - start_offset - 2, 10)
            per_line = available / len(ko_lines)
            for i, text in enumerate(ko_lines):
                start = start_offset + i * per_line
                end_t = min(start + per_line, duration_sec)
                lines.append(
                    f"Dialogue: 0,{_fmt_time(start)},{_fmt_time(end_t)},LyricsKo,,0,0,0,,{text}"
                )

    return "\n".join(lines) + "\n"


def _fmt_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def remaster_audio(input_path: Path, output_path: Path, config: dict) -> Path:
    audio_cfg = config.get("audio", {})
    chain = audio_cfg.get("master_chain", "")
    codec = audio_cfg.get("output_codec", "aac")
    bitrate = audio_cfg.get("output_bitrate", "192k")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-af", chain,
        "-c:a", codec, "-b:a", bitrate,
        str(output_path),
    ]
    _run(cmd)
    return output_path


def _video_encode_args(encoder: str, config: dict) -> list[str]:
    video = config.get("video", {})
    crf = str(video.get("crf", 23))
    if encoder == "h264_amf":
        quality = video.get("amf_quality", "balanced")
        return ["-c:v", "h264_amf", "-quality", quality]
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", crf]
    return ["-c:v", "libx264", "-crf", crf, "-preset", "medium"]


def build_track_video(
    audio_path: Path,
    image_paths: list[Path],
    ass_path: Path,
    output_path: Path,
    config: dict,
) -> Path:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg가 설치되어 있지 않습니다. PATH에 ffmpeg를 추가하세요.")

    video_cfg = config.get("video", {})
    w = video_cfg.get("width", 1920)
    h = video_cfg.get("height", 1080)
    fps = video_cfg.get("fps", 30)
    img_dur = video_cfg.get("image_duration_sec", 8)
    encoder = detect_video_encoder(video_cfg.get("encoder", "auto"))

    duration = probe_duration(audio_path)
    if not image_paths:
        raise ValueError("썸네일 이미지가 필요합니다")

    images = image_paths[:20]
    per_img = max(duration / len(images), img_dur) if len(images) > 1 else duration
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ass_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")

    if len(images) == 1:
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-t", str(duration), "-i", str(images[0]),
            "-i", str(audio_path),
            "-vf", (
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
                f"subtitles='{ass_escaped}':force_style='Alignment=2'"
            ),
            *_video_encode_args(encoder, config),
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output_path),
        ]
        _run(cmd)
        return output_path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        segment_files = []
        for i, img in enumerate(images):
            seg = tmp_path / f"seg_{i:03d}.mp4"
            t = per_img if i < len(images) - 1 else max(duration - per_img * (len(images) - 1), 1)
            cmd = [
                "ffmpeg", "-y", "-loop", "1", "-t", str(t), "-i", str(img),
                "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black",
                *_video_encode_args(encoder, config),
                "-r", str(fps), "-an", str(seg),
            ]
            _run(cmd)
            segment_files.append(seg)

        list_file = tmp_path / "concat.txt"
        list_file.write_text(
            "\n".join(f"file '{s.resolve().as_posix()}'" for s in segment_files),
            encoding="utf-8",
        )
        silent_video = tmp_path / "video_only.mp4"
        _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", str(silent_video),
        ])

        cmd = [
            "ffmpeg", "-y", "-i", str(silent_video), "-i", str(audio_path),
            "-vf", f"subtitles='{ass_escaped}':force_style='Alignment=2'",
            *_video_encode_args(encoder, config),
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output_path),
        ]
        _run(cmd)

    return output_path


def run_full_pipeline(
    project_dir: Path,
    output_dir: Path,
    config: dict | None = None,
) -> dict:
    from app.services.workflow_service import find_project_assets

    cfg = config or get_default_config()
    assets = find_project_assets(project_dir)
    if not assets["audio_paths"]:
        raise ValueError("음원 파일이 없습니다")

    audio_in = Path(assets["audio_paths"][0])
    images = [Path(p) for p in assets["image_paths"]]
    title = assets["track_title"] or project_dir.name

    output_dir.mkdir(parents=True, exist_ok=True)
    remastered = output_dir / "remastered.m4a"
    remaster_audio(audio_in, remastered, cfg)

    duration = probe_duration(remastered)
    ass_content = build_ass_content(
        title,
        assets.get("lyrics_en"),
        assets.get("lyrics_ko"),
        duration,
        cfg,
    )
    ass_path = output_dir / "subtitles.ass"
    ass_path.write_text(ass_content, encoding="utf-8")

    video_out = output_dir / f"{project_dir.name}.mp4"
    build_track_video(remastered, images, ass_path, video_out, cfg)

    meta = {
        "audio_input": str(audio_in),
        "audio_remastered": str(remastered),
        "ass_path": str(ass_path),
        "video_output": str(video_out),
        "encoder": detect_video_encoder(cfg.get("video", {}).get("encoder", "auto")),
        "duration_sec": duration,
    }
    (output_dir / "pipeline_result.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return meta


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "")[-2000:]
        raise RuntimeError(f"FFmpeg 실패: {err}")
