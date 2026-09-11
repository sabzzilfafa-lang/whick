"""로컬 FFmpeg 파이프라인 — 리마스터, 자막, 영상 생성."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from app.services.winproc import creation_flags as _creation_flags

from app.services.pipeline_defaults import get_default_config
from app.services.watermark_service import (
    prepare_watermark_png,
    watermark_overlay_fc,
    watermark_xy,
)

AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"}


def resolve_subtitle_font(config: dict | None = None) -> str:
    """설정값 우선, 없으면 공통 폰트 리졸버 (Windows 맑은고딕 / 번들 Noto Sans KR)."""
    from app.services.font_resolver import ass_font_name

    preferred = str((config or {}).get("subtitle", {}).get("font_name") or "").strip()
    if preferred:
        return preferred
    return ass_font_name()


def resolve_fonts_dir() -> str | None:
    """ASS subtitles 필터 fontsdir — 번들 폰트 우선, 없으면 시스템 폰트 디렉터리."""
    from app.services.font_resolver import ass_fontsdir

    bundled = ass_fontsdir()
    if bundled:
        return bundled
    candidates = [
        Path("C:/Windows/Fonts"),
        Path("/usr/share/fonts/opentype/noto"),
        Path("/usr/share/fonts/truetype/noto"),
        Path("/usr/share/fonts"),
    ]
    for p in candidates:
        if p.is_dir():
            return p.resolve().as_posix().replace(":", "\\:")
    return None


def escape_subtitles_path(ass_path: Path) -> str:
    """ffmpeg subtitles= 필터용 경로 이스케이프."""
    p = ass_path.resolve().as_posix().replace("\\", "/")
    p = p.replace(":", "\\:").replace("'", r"\'").replace(",", "\\,")
    return p


def make_cover_frame(
    img_path: Path,
    out_jpg: Path,
    *,
    bg_w: int = 1920,
    bg_h: int = 1080,
    art_h: int | None = None,
) -> Path:
    """
    WHICK run_music_share_album.make_cover_frame —
    전체 화면 블러 배경 + 중앙 선명 커버(그림자).
    """
    try:
        from PIL import Image, ImageFilter
    except ImportError as e:
        raise RuntimeError("커버 프레임 생성에 Pillow가 필요합니다. pip install pillow") from e

    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    # 서버: 1440p에서 art_h=960 → 비율 유지
    if art_h is None:
        art_h = max(320, int(round(bg_h * (960 / 1440))))

    with Image.open(img_path) as img:
        rgb = img.convert("RGB")
        w, h = rgb.size
        scale = max(bg_w / w, bg_h / h) * 1.12
        bg = rgb.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        left = (bg.width - bg_w) // 2
        top = (bg.height - bg_h) // 2
        bg = bg.crop((left, top, left + bg_w, top + bg_h)).filter(ImageFilter.GaussianBlur(40))
        tint = Image.new("RGBA", (bg_w, bg_h), (10, 12, 16, 150))
        bg = bg.convert("RGBA")
        bg.paste(tint, (0, 0), tint)

        art = rgb.resize((int(w * (art_h / h)), art_h), Image.LANCZOS)
        ax = (bg_w - art.width) // 2
        ay = (bg_h - art.height) // 2 - max(8, bg_h // 72)
        shadow = Image.new("RGBA", (art.width + 50, art.height + 50), (0, 0, 0, 150)).filter(
            ImageFilter.GaussianBlur(22)
        )
        bg.paste(shadow, (ax - 25, ay - 15), shadow)
        bg.paste(art, (ax, ay))
        bg.convert("RGB").save(out_jpg, quality=94)
    return out_jpg


def build_subtitles_vf(ass_path: Path, *, fade_in: float | None = None) -> str:
    """자막 버닝 필터 문자열 (fontsdir 포함).

    주의: 영상에 fade=t=in 을 걸면 인트로가 검게 보이므로 쓰지 않음.
    페이드는 ASS \\fad 만 사용.
    """
    del fade_in  # API 호환 — 비디오 페이드 금지
    escaped = escape_subtitles_path(ass_path)
    fonts = resolve_fonts_dir()
    if fonts:
        return f"subtitles='{escaped}':fontsdir='{fonts}'"
    return f"subtitles='{escaped}'"


def find_ffmpeg() -> str | None:
    try:
        r = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8", errors="replace",
            timeout=10,
            creationflags=_creation_flags(),
        )
        if r.returncode == 0:
            return "ffmpeg"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _encoder_actually_works(encoder: str) -> bool:
    """ffmpeg에 인코더가 '있는지'가 아니라 실제 1프레임 인코딩이 '되는지' 확인.

    NVIDIA GPU가 없어도 ffmpeg 바이너리에는 h264_nvenc가 포함되어 있어
    실제 인코딩 시점에 Cannot load nvcuda.dll 로 실패한다.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "enc_test.mp4"
        try:
            r = subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=duration=0.1:size=320x240:rate=15",
                    "-frames:v", "2",
                    "-c:v", encoder,
                    "-pix_fmt", "yuv420p",
                    str(out),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8", errors="replace",
                timeout=60,
                creationflags=_creation_flags(),
            )
            return r.returncode == 0 and out.exists() and out.stat().st_size > 0
        except (subprocess.TimeoutExpired, OSError):
            return False


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
        encoding="utf-8", errors="replace",
        timeout=15,
        creationflags=_creation_flags(),
    )
    encoders = r.stdout or ""
    # 우선순위: NVIDIA NVENC → AMD AMF → Intel QSV → Intel MF → CPU libx264
    # 단, 인코더가 나열되어 있는 것만으로 부족 — 실제 인코딩 가능 여부까지 검증
    for enc in ("h264_nvenc", "h264_amf", "h264_qsv", "h264_mf"):
        if enc in encoders and _encoder_actually_works(enc):
            return enc
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
        encoding="utf-8", errors="replace",
        timeout=30,
        creationflags=_creation_flags(),
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
    """WHICK ASS SSOT — EN 위 / KO 아래, 시작 TitleCard만."""
    from app.services.ass_subtitle_service import build_whick_ass

    timed_cues = config.get("_timed_cues") or []
    album = str(config.get("_album") or "")
    track_index = config.get("_track_index")
    if track_index is not None:
        try:
            track_index = int(track_index)
        except (TypeError, ValueError):
            track_index = None
    return build_whick_ass(
        track_title=track_title,
        duration_sec=duration_sec,
        cues=timed_cues,
        config=config,
        album=album,
        track_index=track_index,
    )


def _fmt_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def remaster_audio(input_path: Path, output_path: Path, config: dict) -> Path:
    audio_cfg = config.get("audio", {})
    chain = audio_cfg.get("master_chain", "")
    codec = audio_cfg.get("output_codec", "aac")
    bitrate = audio_cfg.get("output_bitrate", "320k")
    strip_meta = bool(audio_cfg.get("strip_fingerprint", True))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(input_path)]
    if strip_meta:
        cmd.extend(["-map_metadata", "-1"])
    cmd.extend([
        "-af", chain,
        "-c:a", codec, "-b:a", bitrate,
        str(output_path),
    ])
    _run(cmd)
    return output_path


def _video_encode_args(encoder: str, config: dict, *, preview_fast: bool = False) -> list[str]:
    if preview_fast:
        return ["-c:v", "libx264", "-crf", "28", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    video = config.get("video", {})
    # YouTube 최종본: 고화질 (CRF 낮을수록 고화질)
    crf = str(min(int(video.get("crf", 17)), 17))
    preset = str(video.get("preset", "slow"))
    if encoder == "h264_amf":
        quality = video.get("amf_quality", "quality")
        return [
            "-c:v", "h264_amf",
            "-quality", quality,
            "-rc", "cqp",
            "-qp_i", crf,
            "-qp_p", crf,
            "-qp_b", str(min(int(crf) + 2, 28)),
            "-pix_fmt", "yuv420p",
        ]
    if encoder == "h264_nvenc":
        nv_preset = str(video.get("nvenc_preset", "p7"))
        return [
            "-c:v", "h264_nvenc",
            "-preset", nv_preset,
            "-rc", "vbr",
            "-cq", crf,
            "-b:v", "0",
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
        ]
    if encoder == "h264_qsv":
        # Intel Quick Sync — ICQ 품질 모드 (crf와 유사한 체감 품질)
        return [
            "-c:v", "h264_qsv",
            "-preset", preset if preset in ("veryfast", "faster", "fast", "medium", "slow") else "medium",
            "-global_quality", crf,
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
        ]
    if encoder == "h264_mf":
        # Windows Media Foundation — 품질 기반 rate control
        return [
            "-c:v", "h264_mf",
            "-rate_control", "quality",
            "-quality", "70",
            "-pix_fmt", "yuv420p",
        ]
    return [
        "-c:v", "libx264",
        "-crf", crf,
        "-preset", preset,
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
    ]


def _audio_mux_args(audio_path: Path, *, preview_fast: bool, bitrate: str) -> list[str]:
    """리마스터 AAC는 재인코딩하지 않고 복사. 미리보기만 낮은 비트레이트로 재압축."""
    if preview_fast:
        return ["-c:a", "aac", "-b:a", bitrate]
    if audio_path.suffix.lower() in {".m4a", ".aac", ".mp4"}:
        return ["-c:a", "copy"]
    return ["-c:a", "aac", "-b:a", bitrate]


def _eq_overlay_fc(
    eq_w: int,
    eq_h: int,
    *,
    align: str,
    eq_x: int,
    eq_y: int,
    bottom_pad: int = 24,
    main: str = "[0:v]",
    eq_in: str = "[1:v]",
    out: str = "outv",
    yuv: bool = True,
) -> str:
    """스펙트럼을 메인 영상에 올림. 하단 중앙은 실제 프레임 기준으로 계산."""
    eq_w = max(8, int(eq_w))
    eq_h = max(8, int(eq_h))
    pad = max(0, int(bottom_pad))
    sized = f"{eq_in}format=rgba,scale={eq_w}:{eq_h}:flags=bilinear[eq]"
    if align == "bottom_center":
        pos = f"x=(W-w)/2:y=H-h-{pad}"
    else:
        pos = f"x={int(eq_x)}:y={int(eq_y)}"
    tail = ",format=yuv420p" if yuv else ""
    ov = f"{main}[eq]overlay={pos}:format=yuv420:shortest=1{tail}[{out}]"
    return f"{sized};{ov}"


def build_track_video(
    audio_path: Path,
    image_paths: list[Path],
    ass_path: Path,
    output_path: Path,
    config: dict,
    *,
    max_duration: float | None = None,
    preview_fast: bool = False,
) -> Path:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg가 설치되어 있지 않습니다. PATH에 ffmpeg를 추가하세요.")

    video_cfg = config.get("video", {})
    overlay_cfg = config.get("overlay", {})
    audio_cfg = config.get("audio", {})
    w = video_cfg.get("width", 1920)
    h = video_cfg.get("height", 1080)
    fps = video_cfg.get("fps", 30)
    img_dur = video_cfg.get("image_duration_sec", 8)
    fade = float(video_cfg.get("fade_in_sec", 0.4))
    encoder = detect_video_encoder(video_cfg.get("encoder", "auto"))
    audio_bitrate = str(audio_cfg.get("output_bitrate", "320k"))
    if preview_fast:
        audio_bitrate = "96k"
    eq_style = str(overlay_cfg.get("eq_bar_style", "none"))
    eq_enabled = eq_style not in ("none", "off", "") and bool(overlay_cfg.get("eq_bar_enabled", True))
    eq_w = int(overlay_cfg.get("eq_bar_w", 1000))
    eq_h = int(overlay_cfg.get("eq_bar_h", 80))
    eq_color = str(overlay_cfg.get("eq_bar_color", "#FFFFFF"))
    eq_align = str(overlay_cfg.get("eq_bar_align") or "bottom_center")
    if eq_align == "bottom_center":
        eq_x = max(0, (w - eq_w) // 2)
        eq_y = max(0, h - eq_h - 24)
    else:
        eq_x = int(overlay_cfg.get("eq_bar_x", (w - eq_w) // 2))
        eq_y = int(overlay_cfg.get("eq_bar_y", max(0, h - eq_h - 24)))
        eq_x = max(0, min(eq_x, max(0, w - eq_w)))
        eq_y = max(0, min(eq_y, max(0, h - eq_h)))

    duration = probe_duration(audio_path)
    if max_duration is not None:
        duration = min(duration, float(max_duration))
    if not image_paths:
        raise ValueError("썸네일 이미지가 필요합니다")

    images = image_paths[:20]
    per_img = max(duration / len(images), img_dur) if len(images) > 1 else duration
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio_args = _audio_mux_args(audio_path, preview_fast=preview_fast, bitrate=audio_bitrate)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ass_local = tmp_path / "subtitles.ass"
        ass_local.write_text(ass_path.read_text(encoding="utf-8"), encoding="utf-8")
        sub_vf = build_subtitles_vf(ass_local, fade_in=fade)

        # 배경 베이스 — 블러 배경 + 중앙 커버 (WHICK make_cover_frame)
        if len(images) == 1:
            bg_scaled = tmp_path / "bg.jpg"
            make_cover_frame(images[0], bg_scaled, bg_w=w, bg_h=h)
            base_inputs = ["-loop", "1", "-framerate", str(fps), "-t", str(duration), "-i", str(bg_scaled)]
        else:
            segment_files = []
            for i, img in enumerate(images):
                frame = tmp_path / f"frame_{i:03d}.jpg"
                make_cover_frame(img, frame, bg_w=w, bg_h=h)
                seg = tmp_path / f"seg_{i:03d}.mp4"
                t = per_img if i < len(images) - 1 else max(duration - per_img * (len(images) - 1), 1)
                cmd = [
                    "ffmpeg", "-y", "-loop", "1", "-t", str(t), "-i", str(frame),
                    "-vf", "format=yuv420p",
                    *_video_encode_args(encoder, config, preview_fast=preview_fast),
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
            base_inputs = ["-i", str(silent_video)]

        eq_path = tmp_path / "eq_bars.mov"
        has_eq = False
        if eq_enabled:
            from app.services.eq_bar_service import make_eq_video

            has_eq = make_eq_video(
                audio_path,
                eq_path,
                width=eq_w,
                height=eq_h,
                style=eq_style,
                max_duration=duration if max_duration is not None else None,
                color=eq_color,
            )

        wm_png = tmp_path / "watermark.png"
        wm = prepare_watermark_png(wm_png, video_h=h)
        wx, wy = watermark_xy(w, h)

        if has_eq:
            fc = _eq_overlay_fc(
                eq_w,
                eq_h,
                align=eq_align,
                eq_x=eq_x,
                eq_y=eq_y,
                bottom_pad=24,
                yuv=False,
            ) + f";[outv]{sub_vf}[vsub]"
            extra_in: list[str] = ["-i", str(eq_path)]
            audio_map = "2:a"
            if wm:
                extra_in += ["-i", str(wm)]
                audio_map = "3:a"
                fc += ";" + watermark_overlay_fc("[vsub]", "[2:v]", "vout", x=wx, y=wy)
            else:
                fc += ";[vsub]format=yuv420p[vout]"
            cmd = [
                "ffmpeg", "-y",
                *base_inputs,
                *extra_in,
                "-i", str(audio_path),
                "-filter_complex", fc,
                "-map", "[vout]", "-map", audio_map,
                *_video_encode_args(encoder, config, preview_fast=preview_fast),
                *audio_args,
                "-shortest",
                "-t", str(duration),
                "-movflags", "+faststart",
                str(output_path),
            ]
        else:
            vf_base = f"[0:v]format=yuv420p,{sub_vf}[vsub]"
            extra_in = []
            audio_map = "1:a"
            if wm:
                extra_in = ["-i", str(wm)]
                audio_map = "2:a"
                fc = vf_base + ";" + watermark_overlay_fc("[vsub]", "[1:v]", "vout", x=wx, y=wy)
            else:
                fc = vf_base + ";[vsub]format=yuv420p[vout]"
            cmd = [
                "ffmpeg", "-y",
                *base_inputs,
                *extra_in,
                "-i", str(audio_path),
                "-filter_complex", fc,
                "-map", "[vout]", "-map", audio_map,
                *_video_encode_args(encoder, config, preview_fast=preview_fast),
                *audio_args,
                "-shortest",
                "-t", str(duration),
                "-movflags", "+faststart",
                str(output_path),
            ]
        _run(cmd)

    return output_path


def run_full_pipeline(
    project_dir: Path,
    output_dir: Path,
    config: dict | None = None,
    progress_cb=None,
) -> dict:
    from app.services.workflow_service import find_project_assets, pick_track_cover, remember_pipeline_output

    def _prog(msg: str):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    cfg = config or get_default_config()
    from app.services.editor_service import merge_editor_into_pipeline

    cfg = merge_editor_into_pipeline(project_dir, cfg)
    # YouTube 최종본: 저장된 구설정이 있어도 최고 화질·음질로 고정
    video = cfg.setdefault("video", {})
    video["crf"] = min(int(video.get("crf", 17) or 17), 17)
    video["preset"] = "slow"
    video["amf_quality"] = "quality"
    video["nvenc_preset"] = "p7"
    audio = cfg.setdefault("audio", {})
    audio["output_bitrate"] = "320k"
    assets = find_project_assets(project_dir)
    if not assets["audio_paths"]:
        raise ValueError("음원 파일이 없습니다")

    # 사전 점검: 커버·가사 누락 시 인코딩 전에 중단.
    # 자막 모드가 요구하는 언어 가사(both→en+ko, en→en, ko→ko)도 함께 검사.
    from app.services.preflight_service import preflight_single_track

    preflight_single_track(project_dir, (cfg.get("subtitle") or {}).get("mode"))

    audio_in = Path(assets["audio_paths"][0])
    cover = pick_track_cover(assets)
    if not cover:
        raise ValueError("커버 이미지가 없습니다 (thumbnail.jpg는 유튜브 목록용입니다)")
    images = [cover]
    title = assets["track_title"] or project_dir.name

    output_dir.mkdir(parents=True, exist_ok=True)
    remastered = output_dir / "remastered.m4a"
    _prog("리마스터 중...")
    remaster_audio(audio_in, remastered, cfg)

    duration = probe_duration(remastered)
    from app.services.lyric_timing_service import align_track_lyrics, get_whisper_model

    _prog("가사 싱크(Whisper) 준비...")
    whisper = get_whisper_model()
    _prog("가사 싱크 정렬 중...")
    timed = align_track_lyrics(
        remastered,
        assets.get("lyrics_en"),
        assets.get("lyrics_ko"),
        duration,
        cache_dir=project_dir,
        cache_source=audio_in,
        whisper_model=whisper,
    )

    # 사후 검증: 큐 0개 / 커버리지 부족 / 역전·겹침 — 인코딩 전에 중단
    from app.services.preflight_service import validate_aligned_cues

    single_track_ctx = [
        {
            "start": 0.0,
            "end": duration,
            "title": title,
            "lyrics_en": assets.get("lyrics_en"),
            "lyrics_ko": assets.get("lyrics_ko"),
        }
    ]
    absolute_cues = [
        {**c, "start": float(c["start"]), "end": float(c["end"])} for c in timed
    ]
    validate_aligned_cues(absolute_cues, single_track_ctx)

    cfg_with_cues = {**cfg, "_timed_cues": timed}
    from app.services.ass_subtitle_service import infer_album_and_track

    album, idx = infer_album_and_track(project_dir)
    cfg_with_cues["_album"] = album
    cfg_with_cues["_track_index"] = idx
    ass_content = build_ass_content(
        title,
        assets.get("lyrics_en"),
        assets.get("lyrics_ko"),
        duration,
        cfg_with_cues,
    )
    ass_path = output_dir / "subtitles.ass"
    ass_path.write_text(ass_content, encoding="utf-8")
    (output_dir / "lyrics_timing.json").write_text(
        json.dumps(timed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if not images:
        raise ValueError("썸네일 이미지가 없습니다")

    _prog("영상 인코딩·자막 버닝 중...")
    video_out = output_dir / f"{project_dir.name}.mp4"
    build_track_video(remastered, images, ass_path, video_out, cfg)

    meta = {
        "audio_input": str(audio_in),
        "audio_remastered": str(remastered),
        "ass_path": str(ass_path),
        "video_output": str(video_out),
        "encoder": detect_video_encoder(cfg.get("video", {}).get("encoder", "auto")),
        "duration_sec": duration,
        "lyric_cues": len(timed),
    }
    (output_dir / "pipeline_result.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    remember_pipeline_output(project_dir, video_out, {"output_dir": str(output_dir)})
    return meta


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600, creationflags=_creation_flags())
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "")
        # swscaler 경고, 폰트 선택, Using font provider 등 잡음 제거 — 진짜 에러만
        lines = []
        for line in err.splitlines():
            low = line.lower()
            if "deprecated pixel format" in low:
                continue
            if "fontselect:" in low:
                continue
            if "using font provider" in low:
                continue
            lines.append(line)
        clean = "\n".join(lines).strip()
        if not clean:
            clean = err[-2000:]
        raise RuntimeError(f"FFmpeg 실패: {clean}")
