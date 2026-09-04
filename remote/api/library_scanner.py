"""로컬 FLAC/WAV/MP3 라이브러리 스캔 — 체험 플레이어 parseTrackMeta 규칙 SSOT."""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import asyncpg

AUDIO_EXTS = {
    ".flac", ".wav", ".mp3", ".aac", ".m4a", ".ogg", ".oga", ".opus",
    ".aiff", ".aif", ".alac", ".ape", ".wv", ".wma", ".dsf", ".dff",
}
DSD_EXT = {".dsf", ".dff"}
LOSSY_EXT = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wma"}
LOSSLESS_EXT = {".flac", ".wav", ".aiff", ".aif", ".alac", ".wv", ".ape", ".dsf", ".dff"}
HIRES_MIN_BIT_DEPTH = int(os.getenv("WHICK_HIRES_MIN_BIT_DEPTH", "24"))
HIRES_MIN_SAMPLE_RATE = int(os.getenv("WHICK_HIRES_MIN_SAMPLE_RATE", "88200"))
HIRES_ALLOW_FLAC_24_48 = os.getenv("WHICK_HIRES_ALLOW_FLAC_24_48", "1") != "0"
DEFAULT_SCAN_PATHS = (
    "/var/lib/whick/library/music",
)
AUDIT_SETTINGS_PATH = Path(
    os.getenv(
        "WHICK_LIBRARY_AUDIT_SETTINGS",
        "/var/lib/whick/state/library-audit-settings.json",
    )
)
AUDIT_LEVELS = {
    "hires": [
        {"label": "24bit / 48kHz 이상", "bit_depth": 24, "sample_rate": 48000},
        {"label": "24bit / 96kHz 이상", "bit_depth": 24, "sample_rate": 96000},
        {"label": "24bit / 192kHz 이상", "bit_depth": 24, "sample_rate": 192000},
    ],
    "flac": [
        {"label": "16bit / 44.1kHz 이상", "bit_depth": 16, "sample_rate": 44100},
        {"label": "16bit / 48kHz 이상", "bit_depth": 16, "sample_rate": 48000},
        {"label": "24bit / 48kHz 이상", "bit_depth": 24, "sample_rate": 48000},
        {"label": "24bit / 96kHz 이상", "bit_depth": 24, "sample_rate": 96000},
        {"label": "24bit / 192kHz 이상", "bit_depth": 24, "sample_rate": 192000},
    ],
    "mp3": [
        {"label": "192kbps 이상", "bit_rate": 192000},
        {"label": "256kbps 이상", "bit_rate": 256000},
        {"label": "320kbps", "bit_rate": 320000},
    ],
}
DEFAULT_AUDIT_SETTINGS = {
    "enabled": {"hires": False, "flac": False, "mp3": False},
    "levels": {"hires": 0, "flac": 0, "mp3": 0},
    "empty_selection": "allow_all",
}


@dataclass
class ScanResult:
    scanned_files: int = 0
    upserted: int = 0
    removed: int = 0
    total_tracks: int = 0
    audited: int = 0
    audit_passed: int = 0
    audit_rejected: int = 0
    audit_reasons: dict = None
    classified: int = 0       # robot-classifier 분류 완료
    classified_tiers: dict = None  # {tier: count}
    classified_formats: dict = None
    duplicate_skipped: int = 0  # 등록 라이브러리 artist+title 중복 스킵

    def __post_init__(self):
        self.audit_reasons = self.audit_reasons or {}
        self.classified_tiers = self.classified_tiers or {}
        self.classified_formats = self.classified_formats or {}


def track_identity_key(artist: str | None, title: str | None) -> str:
    """등록 라이브러리 중복 판정 키 (artist + title)."""
    a = " ".join(str(artist or "").strip().lower().split())
    t = " ".join(str(title or "").strip().lower().split())
    if not a and not t:
        return ""
    return f"{a}::{t}"


async def load_registered_identity_map(conn: asyncpg.Connection) -> dict[str, str]:
    """이미 등록된 라이브러리 identity → file_path (먼저 등록된 경로 유지)."""
    rows = await conn.fetch("SELECT title, artist, file_path FROM tracks")
    out: dict[str, str] = {}
    for row in rows:
        key = track_identity_key(row["artist"], row["title"])
        if key and key not in out:
            out[key] = row["file_path"]
    return out


def is_duplicate_of_registered(
    meta: dict,
    registered: dict[str, str],
    *,
    seen_in_batch: dict[str, str] | None = None,
) -> bool:
    """등록 라이브러리(또는 같은 배치)에 동일 artist+title·다른 경로가 있으면 True."""
    key = track_identity_key(meta.get("artist"), meta.get("title"))
    if not key:
        return False
    fp = str(meta.get("file_path") or "")
    existing = None
    if seen_in_batch and key in seen_in_batch:
        existing = seen_in_batch[key]
    elif key in registered:
        existing = registered[key]
    if existing and existing != fp:
        return True
    return False


def audit_settings_schema() -> dict:
    return {
        "enabled": dict(DEFAULT_AUDIT_SETTINGS["enabled"]),
        "levels": dict(DEFAULT_AUDIT_SETTINGS["levels"]),
        "empty_selection": "allow_all",
        "choices": AUDIT_LEVELS,
    }


def normalize_audit_settings(raw: dict | None) -> dict:
    source = raw if isinstance(raw, dict) else {}
    enabled_raw = source.get("enabled") if isinstance(source.get("enabled"), dict) else {}
    levels_raw = source.get("levels") if isinstance(source.get("levels"), dict) else {}
    enabled: dict[str, bool] = {}
    levels: dict[str, int] = {}
    for key, choices in AUDIT_LEVELS.items():
        enabled[key] = bool(enabled_raw.get(key, DEFAULT_AUDIT_SETTINGS["enabled"][key]))
        try:
            level = int(levels_raw.get(key, DEFAULT_AUDIT_SETTINGS["levels"][key]))
        except (TypeError, ValueError):
            level = 0
        levels[key] = max(0, min(level, len(choices) - 1))
    return {
        "enabled": enabled,
        "levels": levels,
        "empty_selection": "allow_all",
    }


def load_audit_settings() -> dict:
    if not AUDIT_SETTINGS_PATH.is_file():
        return normalize_audit_settings(None)
    try:
        return normalize_audit_settings(
            json.loads(AUDIT_SETTINGS_PATH.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError):
        return normalize_audit_settings(None)


def save_audit_settings(raw: dict | None) -> dict:
    settings = normalize_audit_settings(raw)
    AUDIT_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = AUDIT_SETTINGS_PATH.with_suffix(".tmp")
    temp.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(AUDIT_SETTINGS_PATH)
    return settings


def scan_paths_from_env() -> list[Path]:
    """MPD 재생 가능 경로만 — incoming은 import-incoming 후 별도 scan."""
    raw = os.getenv("WHICK_LIBRARY_SCAN_PATHS", "")
    parts = [p.strip() for p in raw.split(":") if p.strip()] if raw else list(DEFAULT_SCAN_PATHS)
    return [Path(p) for p in parts]


def _path_under_root(file_path: str, root: str) -> bool:
    try:
        Path(file_path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _clean_track_title(name: str) -> str:
    s = str(name or "")
    s = re.sub(r"\s*ƒ_.+$", "", s, flags=re.I)
    s = re.sub(r"~.+$", "", s, flags=re.I)
    s = re.sub(r"\.flac$", "", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def _tag_text(value) -> str:
    """Vorbis/ID3 태그 → 표시용 문자열 (멀티값 join)."""
    if value is None:
        return ""
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if str(v).strip()]
        return "; ".join(parts)
    if hasattr(value, "text"):  # ID3Frame
        try:
            parts = [str(t).strip() for t in value.text if str(t).strip()]
            return "; ".join(parts) if parts else str(value)
        except Exception:
            return str(value)
    return str(value).strip()


def _humanize_camel(name: str) -> str:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", name or "")
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_trial_filename(stem: str, path: Path) -> dict[str, str]:
    """체험 whick-trial-player.js parseTrackMeta — 로컬·샘플 FLAC 파일명."""
    raw = str(stem or "").replace(".flac", "").strip()
    rel = str(path).replace("\\", "/")
    is_local_import = "/incoming/" in rel or "/music/local/" in rel

    if is_local_import:
        return {
            "title": raw,
            "artist": "My Music",
            "album": "Local Library",
            "genre": "Local",
        }

    artist = "Sample"
    album = "Sample Collection"
    track_title = raw

    m_album = re.match(r"^Hi-Res•(.+?)_(\d{1,3})\.\s*(.+)$", raw, re.I)
    if m_album and "ƒ" not in m_album.group(1) and "~" not in m_album.group(1):
        album = m_album.group(1).strip()
        artist = album
        track_title = _clean_track_title(m_album.group(3))
    elif re.search(r"\s*ƒ_", raw, re.I):
        m_simple = re.match(r"^Hi-Res•(.+?)\s*ƒ_(.+)$", raw, re.I)
        if m_simple:
            album = m_simple.group(1).strip()
            artist = album
            track_title = _clean_track_title(m_simple.group(2)) or album

    if track_title == raw:
        if " - " in raw:
            parts = [p.strip() for p in raw.split(" - ")]
            artist = parts[0]
            album = parts[1] if len(parts) > 2 else parts[0]
            track_title = parts[-1]
        elif "•" in raw:
            seg = raw.split("•", 1)
            if len(seg) > 1:
                album = seg[1].split("_")[0].strip()
                artist = album
        elif "-" in raw and " " not in raw.split("-", 1)[0]:
            # ComposerCamelCase-WorkTitle.flac (seed-music)
            left, right = raw.split("-", 1)
            if left and right and re.search(r"[A-Z]", left):
                artist = _humanize_camel(left)
                track_title = _humanize_camel(right)
                album = "Whick Sample"

    return {
        "title": track_title or raw,
        "artist": artist or "Unknown",
        "album": album or "Unknown",
        "genre": "Classical" if ("Hi-Res" in raw or artist not in ("Sample", "My Music")) else "Local",
    }


def _read_mutagen(path: Path) -> dict:
    out: dict = {}
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(path)
        if not audio:
            return out
        info = audio.info
        if info and getattr(info, "length", None):
            out["duration_sec"] = int(info.length)
        if info and getattr(info, "bits_per_sample", None):
            out["bit_depth"] = int(info.bits_per_sample)
        if info and getattr(info, "sample_rate", None):
            out["sample_rate"] = int(info.sample_rate)

        tags = audio.tags or {}
        if hasattr(tags, "get"):
            title = tags.get("title") or tags.get("TIT2")
            artist = tags.get("artist") or tags.get("TPE1")
            album = tags.get("album") or tags.get("TALB")
            genre = tags.get("genre") or tags.get("TCON")
            date = tags.get("date") or tags.get("TDRC")
            composer = (
                tags.get("composer")
                or tags.get("COMPOSER")
                or tags.get("TCOM")
                or tags.get("©wrt")
            )
            title_s = _tag_text(title)
            artist_s = _tag_text(artist)
            album_s = _tag_text(album)
            genre_s = _tag_text(genre)
            composer_s = _tag_text(composer)
            if title_s:
                out["title"] = title_s
            if genre_s:
                out["genre"] = genre_s
            if album_s:
                out["album"] = album_s
            if composer_s:
                out["composer"] = composer_s
            # 클래식/작곡가 태그: 표시 artist = 작곡가 (오케스트라만 보이던 문제)
            genre_l = genre_s.lower()
            classical = "classical" in genre_l or "클래식" in genre_l or bool(composer_s)
            if classical and composer_s:
                out["artist"] = composer_s
                if artist_s and artist_s.lower() not in composer_s.lower():
                    out["performer"] = artist_s
            elif artist_s:
                out["artist"] = artist_s
            if date:
                m = re.search(r"(\d{4})", _tag_text(date))
                if m:
                    out["year"] = int(m.group(1))
    except Exception as exc:
        print(f"[library] mutagen skip {path.name}: {exc}")
    return out


try:
    from api.dsd_playback import dsd_format_from_rate
except ImportError:
    def dsd_format_from_rate(raw_rate: int) -> str:
        """dsd_format_from_rate fallback — dsd_playback 미설치 시."""
        rates = [(22579200, "DSD512"), (11289600, "DSD256"), (5644800, "DSD128"), (2822400, "DSD64")]
        for threshold, label in rates:
            if raw_rate >= threshold:
                return label
        return "DSD"


def extract_track_meta(path: Path) -> dict:
    ext = path.suffix.lower()
    fmt = {"m4a": "AAC", "aif": "AIFF", "dsf": "DSD", "dff": "DSD"}.get(
        ext.lstrip("."), ext.lstrip(".").upper()
    )
    meta = _read_mutagen(path)
    if ext in DSD_EXT or ext in {".ape", ".wv", ".wma", ".aiff", ".aif", ".alac"} or not meta.get("sample_rate"):
        probe = _probe_audio(path)
        if probe.get("ok"):
            if probe.get("sample_rate"):
                meta["sample_rate"] = probe["sample_rate"]
            if probe.get("bit_depth"):
                meta["bit_depth"] = probe["bit_depth"]
            if probe.get("duration") and not meta.get("duration_sec"):
                meta["duration_sec"] = int(probe["duration"])
            if ext in DSD_EXT:
                fmt = dsd_format_from_rate(int(probe.get("sample_rate") or 0))
                meta["bit_depth"] = 1
    parsed = parse_trial_filename(path.stem, path)

    title = meta.get("title") or parsed["title"]
    artist = meta.get("artist") or parsed["artist"]
    album = meta.get("album") or parsed["album"]
    genre = meta.get("genre") or parsed.get("genre")
    composer = meta.get("composer")
    if not composer and genre and ("classical" in str(genre).lower() or "클래식" in str(genre)):
        composer = artist
    # Musopen 공통 앨범명 → 샘플 컬렉션으로 정리
    if album and "musopen" in album.lower():
        album = "Whick Sample"
        if not genre:
            genre = "Classical"
        if not composer and artist:
            composer = artist
    license_tag = "Sample" if "/samples/" in str(path).replace("\\", "/") else "Local"

    return {
        "title": title,
        "artist": artist,
        "album": album,
        "genre": genre,
        "composer": composer,
        "year": meta.get("year"),
        "duration_sec": meta.get("duration_sec"),
        "bit_depth": meta.get("bit_depth"),
        "sample_rate": meta.get("sample_rate"),
        "format": fmt,
        "file_path": str(path.resolve()),
        "file_size": path.stat().st_size,
        "license": license_tag,
    }


def _skip_library_path(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    if "tones" in parts:
        return True
    name = path.name.lower()
    return name.startswith("test-") or name == "log-sweep.wav"


def iter_audio_files(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for root in paths:
        if not root.is_dir():
            continue
        for file in root.rglob("*"):
            if not file.is_file():
                continue
            if file.suffix.lower() not in AUDIO_EXTS:
                continue
            if _skip_library_path(file):
                continue
            key = str(file.resolve())
            if key in seen:
                continue
            seen.add(key)
            found.append(file)
    return found


async def upsert_track(conn: asyncpg.Connection, meta: dict) -> None:
    await conn.execute(
        """
        INSERT INTO tracks
          (title, artist, album, genre, year, duration_sec, bit_depth, sample_rate,
           format, file_path, file_size, license, quality, quality_reasons, composer,
           storage_source, search_keywords)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
        ON CONFLICT (file_path) DO UPDATE SET
          title = EXCLUDED.title,
          artist = EXCLUDED.artist,
          album = EXCLUDED.album,
          genre = EXCLUDED.genre,
          year = EXCLUDED.year,
          duration_sec = COALESCE(EXCLUDED.duration_sec, tracks.duration_sec),
          bit_depth = COALESCE(EXCLUDED.bit_depth, tracks.bit_depth),
          sample_rate = COALESCE(EXCLUDED.sample_rate, tracks.sample_rate),
          format = EXCLUDED.format,
          file_size = EXCLUDED.file_size,
          license = EXCLUDED.license,
          quality = COALESCE(EXCLUDED.quality, tracks.quality),
          quality_reasons = COALESCE(EXCLUDED.quality_reasons, tracks.quality_reasons),
          composer = COALESCE(EXCLUDED.composer, tracks.composer),
          storage_source = COALESCE(EXCLUDED.storage_source, tracks.storage_source),
          search_keywords = COALESCE(NULLIF(EXCLUDED.search_keywords, ''), tracks.search_keywords)
        """,
        meta["title"],
        meta["artist"],
        meta["album"],
        meta.get("genre"),
        meta.get("year"),
        meta.get("duration_sec"),
        meta.get("bit_depth"),
        meta.get("sample_rate"),
        meta["format"],
        meta["file_path"],
        meta["file_size"],
        meta.get("license"),
        meta.get("quality"),
        meta.get("quality_reasons"),
        meta.get("composer"),
        meta.get("storage_source") or "internal",
        meta.get("search_keywords") or None,
    )


async def scan_library(pool: asyncpg.Pool, paths: list[Path] | None = None) -> ScanResult:
    roots = paths or scan_paths_from_env()
    files = iter_audio_files(roots)
    seen_paths = set()
    seen_identities: dict[str, str] = {}
    result = ScanResult(scanned_files=len(files))
    audit_settings = load_audit_settings()

    async with pool.acquire() as conn:
        registered = await load_registered_identity_map(conn)
        for path in files:
            try:
                meta = extract_track_meta(path)
                # 검수로봇: 고객이 선택한 형식·최소 품질의 합집합만 통과.
                audit = evaluate_audit_settings(path, audit_settings)
                result.audited += 1
                if not audit["pass"]:
                    result.audit_rejected += 1
                    for reason in audit.get("reasons") or ["quality_below_threshold"]:
                        result.audit_reasons[reason] = result.audit_reasons.get(reason, 0) + 1
                    continue
                result.audit_passed += 1

                # 등록 라이브러리 참조 중복 제거 (동일 artist+title · 다른 파일 경로)
                if is_duplicate_of_registered(meta, registered, seen_in_batch=seen_identities):
                    result.duplicate_skipped += 1
                    print(
                        f"[library] duplicate skip {meta.get('file_path')} "
                        f"({meta.get('artist')} — {meta.get('title')})"
                    )
                    continue

                # 분류로봇: 통과 음원의 품질 등급·형식·메타데이터 분류.
                verdict = evaluate_hires(path)
                meta["quality"] = verdict.get("tier", "unknown")
                meta["quality_reasons"] = json.dumps(verdict.get("reasons") or [])

                # AI 검색 보조 키워드 — 없거나(실패/미생성) 구버전처럼 과다하면
                # 재생성. 정상(≤5토큰)이면 재호출하지 않는다.
                existing_kw = await conn.fetchval(
                    "SELECT search_keywords FROM tracks WHERE file_path = $1",
                    meta["file_path"],
                )
                kw_tokens = [t for t in str(existing_kw or "").split() if t]
                need_keywords = not existing_kw or len(kw_tokens) > 5
                if need_keywords:
                    try:
                        from api.ollama_client import generate_track_search_keywords

                        generated = await generate_track_search_keywords(meta)
                        if generated:
                            meta["search_keywords"] = generated
                    except Exception as exc:
                        print(f"[classify] search_keywords 생성 실패 {meta['file_path']}: {exc}")
                    if not meta.get("search_keywords"):
                        from api.search_expand import seed_keywords_for_meta

                        seeded = seed_keywords_for_meta(
                            str(meta.get("title") or ""),
                            str(meta.get("composer") or ""),
                            str(meta.get("artist") or ""),
                        )
                        if seeded:
                            meta["search_keywords"] = seeded
                        else:
                            # 빈 문자열로 기존 키워드를 덮지 않음
                            meta.pop("search_keywords", None)

                await upsert_track(conn, meta)
                seen_paths.add(meta["file_path"])
                ident = track_identity_key(meta.get("artist"), meta.get("title"))
                if ident:
                    seen_identities[ident] = meta["file_path"]
                    registered[ident] = meta["file_path"]
                result.upserted += 1
                result.classified += 1
                tier = verdict.get("tier", "unknown")
                result.classified_tiers[tier] = result.classified_tiers.get(tier, 0) + 1
                fmt = str(meta.get("format") or path.suffix.lstrip(".") or "unknown").upper()
                result.classified_formats[fmt] = result.classified_formats.get(fmt, 0) + 1
            except Exception as exc:
                print(f"[library] skip {path}: {exc}")

        prefixes = [str(r.resolve()) for r in roots if r.is_dir()]
        library_root = "/var/lib/whick/library/"
        if prefixes:
            try:
                rows = await conn.fetch("SELECT track_id, file_path, storage_source FROM tracks")
            except asyncpg.UndefinedColumnError:
                rows = await conn.fetch("SELECT track_id, file_path FROM tracks")
            except asyncpg.UndefinedTableError:
                print("[library] tracks table missing — skip stale cleanup")
                return result
            remove_ids = []
            for row in rows:
                fp = row["file_path"]
                if fp in seen_paths:
                    continue
                # 외장 경로 등록곡은 일반 music 스캔에서 삭제하지 않음
                src = ""
                try:
                    src = str(row.get("storage_source") or "")
                except Exception:
                    src = ""
                if src == "external" or str(fp).startswith("/media/") or str(fp).startswith("/run/media/"):
                    # 파일 없으면 목록에서만 제거
                    if not Path(fp).is_file():
                        remove_ids.append(row["track_id"])
                    continue
                under_scan = any(_path_under_root(fp, prefix) for prefix in prefixes)
                if under_scan:
                    remove_ids.append(row["track_id"])
                elif fp.startswith(library_root):
                    remove_ids.append(row["track_id"])
            if remove_ids:
                # FK constraint: play_history, favorites 등이 tracks를 참조하므로 먼저 정리
                await conn.execute("DELETE FROM play_history WHERE track_id = ANY($1::bigint[])", remove_ids)
                await conn.execute("DELETE FROM favorites WHERE track_id = ANY($1::bigint[])", remove_ids)
                await conn.execute("DELETE FROM playlist_tracks WHERE track_id = ANY($1::bigint[])", remove_ids)
                await conn.execute("DELETE FROM tracks WHERE track_id = ANY($1::bigint[])", remove_ids)
                result.removed = len(remove_ids)

        result.total_tracks = int(await conn.fetchval("SELECT COUNT(*) FROM tracks") or 0)

    print(
        f"[library] scan files={result.scanned_files} upserted={result.upserted} "
        f"duplicate_skipped={result.duplicate_skipped} "
        f"removed={result.removed} total={result.total_tracks} "
        f"audited={result.audited} passed={result.audit_passed} "
        f"rejected={result.audit_rejected} classified={result.classified} "
        f"tiers={result.classified_tiers}"
    )
    return result


def _probe_audio(file_path: Path) -> dict:
    try:
        raw = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name,sample_rate,bits_per_raw_sample,bits_per_sample,channels,duration,bit_rate",
                "-of",
                "json",
                str(file_path),
            ],
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        data = json.loads(raw)
        stream = (data.get("streams") or [{}])[0]
        bit_depth = int(stream.get("bits_per_raw_sample") or stream.get("bits_per_sample") or 0)
        return {
            "ok": True,
            "codec": stream.get("codec_name") or "",
            "sample_rate": int(stream.get("sample_rate") or 0),
            "bit_depth": bit_depth,
            "channels": int(stream.get("channels") or 0),
            "duration": float(stream.get("duration") or 0),
            "bit_rate": int(stream.get("bit_rate") or 0),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def evaluate_hires(file_path: Path) -> dict:
    """Hi-res 판정 — 파일 변경 없음 (robot-auditor SSOT)."""
    ext = file_path.suffix.lower()
    base = {"file": str(file_path), "ext": ext, "pass": False, "tier": "reject", "reasons": []}

    if ext in LOSSY_EXT:
        base["reasons"].append("lossy_format")
        return base
    if ext not in LOSSLESS_EXT:
        base["reasons"].append("unknown_extension")
        return base

    if ext in DSD_EXT:
        probe = _probe_audio(file_path)
        if probe.get("ok"):
            base["probe"] = {
                "codec": probe["codec"],
                "sample_rate": probe["sample_rate"],
                "bit_depth": 1,
                "channels": probe["channels"],
                "duration": probe["duration"],
            }
            base["pass"] = True
            base["tier"] = "dsd"
        else:
            base["reasons"].append("probe_failed")
        return base

    probe = _probe_audio(file_path)
    if not probe.get("ok"):
        base["reasons"].append("probe_failed")
        return base

    base["probe"] = {
        "codec": probe["codec"],
        "sample_rate": probe["sample_rate"],
        "bit_depth": probe["bit_depth"],
        "channels": probe["channels"],
        "duration": probe["duration"],
    }

    bd = probe["bit_depth"] or (16 if ext == ".flac" else 0)
    sr = probe["sample_rate"]
    hires_by_rate = sr >= HIRES_MIN_SAMPLE_RATE
    hires_by_depth = bd >= HIRES_MIN_BIT_DEPTH
    flac_24_48 = HIRES_ALLOW_FLAC_24_48 and ext == ".flac" and bd >= 24 and sr >= 48000

    if hires_by_rate or hires_by_depth or flac_24_48:
        base["pass"] = True
        base["tier"] = "hires-rate" if hires_by_rate else "hires-depth" if hires_by_depth else "hires-24-48"
        return base

    if bd >= 16 and sr >= 44100:
        base["tier"] = "cd"
        base["pass"] = True
        return base
    base["reasons"].append("below_hires_threshold")
    return base


def evaluate_audit_settings(file_path: Path, settings: dict | None = None) -> dict:
    """사용자 검수 기준. 선택 항목은 OR(합집합), 모두 꺼짐은 전체 허용."""
    normalized = normalize_audit_settings(settings)
    enabled = normalized["enabled"]
    selected = [key for key, active in enabled.items() if active]
    if not selected:
        return {
            "pass": True,
            "enabled": False,
            "matched": ["allow_all"],
            "reasons": [],
        }

    ext = file_path.suffix.lower()
    probe = _probe_audio(file_path)
    bit_depth = int(probe.get("bit_depth") or 0)
    sample_rate = int(probe.get("sample_rate") or 0)
    bit_rate = int(probe.get("bit_rate") or 0)
    matched: list[str] = []
    below: list[str] = []

    if enabled["hires"] and ext in LOSSLESS_EXT:
        level = AUDIT_LEVELS["hires"][normalized["levels"]["hires"]]
        if ext in DSD_EXT or (
            bit_depth >= int(level["bit_depth"])
            and sample_rate >= int(level["sample_rate"])
        ):
            matched.append("hires")
        else:
            below.append("hires_below_threshold")

    if enabled["flac"] and ext == ".flac":
        level = AUDIT_LEVELS["flac"][normalized["levels"]["flac"]]
        if (
            bit_depth >= int(level["bit_depth"])
            and sample_rate >= int(level["sample_rate"])
        ):
            matched.append("flac")
        else:
            below.append("flac_below_threshold")

    if enabled["mp3"] and ext == ".mp3":
        level = AUDIT_LEVELS["mp3"][normalized["levels"]["mp3"]]
        # ffprobe의 평균 비트레이트 반올림 오차(예: 319.9kbps)를 허용한다.
        if bit_rate >= int(level["bit_rate"]) - 5000:
            matched.append("mp3")
        else:
            below.append("mp3_below_threshold")

    if matched:
        return {
            "pass": True,
            "enabled": True,
            "matched": matched,
            "reasons": [],
            "probe": {
                "bit_depth": bit_depth,
                "sample_rate": sample_rate,
                "bit_rate": bit_rate,
            },
        }

    reasons = below or ["format_not_selected"]
    if not probe.get("ok") and ext in {".flac", ".mp3"} | (LOSSLESS_EXT - DSD_EXT):
        reasons = ["probe_failed"]
    return {
        "pass": False,
        "enabled": True,
        "matched": [],
        "reasons": reasons,
        "probe": {
            "bit_depth": bit_depth,
            "sample_rate": sample_rate,
            "bit_rate": bit_rate,
        },
    }


def audit_incoming_files(incoming: Path, rel_paths: list[str] | None = None) -> dict:
    """incoming 음원 검수 — 결과만 반환, 파일 이동·삭제 없음."""
    incoming.mkdir(parents=True, exist_ok=True)
    wanted = {p.strip().lstrip("/") for p in (rel_paths or []) if p and str(p).strip()}
    items: list[dict] = []
    approved: list[str] = []
    rejected: list[str] = []
    audit_settings = load_audit_settings()

    for file in incoming.rglob("*"):
        if not file.is_file() or file.suffix.lower() not in AUDIO_EXTS:
            continue
        rel = str(file.relative_to(incoming)).replace("\\", "/")
        if wanted and rel not in wanted:
            continue
        audit = evaluate_audit_settings(file, audit_settings)
        quality = evaluate_hires(file)
        item = {
            "rel_path": rel,
            "verdict": "approved" if audit["pass"] else "rejected",
            "tier": quality.get("tier"),
            "reasons": audit.get("reasons") or [],
            "probe": audit.get("probe") or quality.get("probe"),
        }
        items.append(item)
        if audit["pass"]:
            approved.append(rel)
        else:
            rejected.append(rel)

    return {
        "mode": "audit_only",
        "files_modified": False,
        "robot": "robot-auditor",
        "approved": len(approved),
        "rejected": len(rejected),
        "reviewed_files": approved,
        "rejected_files": rejected,
        "items": items,
    }


def import_incoming_files(
    incoming: Path,
    music_root: Path,
    approved_paths: list[str] | None = None,
) -> dict:
    """incoming → music_root 바로 아래 저장 — 사용자 승인(approved_paths) 후에만 이동."""
    incoming.mkdir(parents=True, exist_ok=True)
    dest_root = music_root
    dest_root.mkdir(parents=True, exist_ok=True)
    allowed = {p.strip().lstrip("/") for p in (approved_paths or []) if p and str(p).strip()}
    if not allowed:
        return {"moved": 0, "paths": [], "skipped": "no_approved_paths"}

    moved = []
    for file in incoming.rglob("*"):
        if not file.is_file() or file.suffix.lower() not in AUDIO_EXTS:
            continue
        rel = str(file.relative_to(incoming)).replace("\\", "/")
        if rel not in allowed:
            continue
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest = dest_root / f"{file.stem}_{file.stat().st_mtime_ns}{file.suffix}"
        file.rename(dest)
        moved.append(str(dest))
    return {"moved": len(moved), "paths": moved[:20]}


def delete_incoming_files(incoming: Path, paths: list[str]) -> dict:
    """incoming 내 지정 파일 삭제 — 사용자 명시 승인 후에만 호출."""
    incoming.mkdir(parents=True, exist_ok=True)
    deleted: list[str] = []
    for rel in paths:
        rel = str(rel or "").strip().lstrip("/")
        if not rel or ".." in Path(rel).parts:
            continue
        target = (incoming / rel).resolve()
        if not str(target).startswith(str(incoming.resolve())):
            continue
        if target.is_file():
            target.unlink()
            deleted.append(rel)
    return {"deleted": len(deleted), "paths": deleted[:20]}


def _storage_source_for_path(path: Path) -> str:
    ps = str(path.resolve())
    if ps.startswith("/media/") or ps.startswith("/run/media/"):
        return "external"
    return "internal"


async def register_audio_files(pool: asyncpg.Pool, files: list[Path], *, run_audit: bool = False) -> dict:
    """경로만 라이브러리에 등록 (복사 없음). 등록 라이브러리 artist+title 중복은 스킵."""
    upserted = 0
    skipped = 0
    duplicate_skipped = 0
    async with pool.acquire() as conn:
        registered = await load_registered_identity_map(conn)
        seen_identities: dict[str, str] = {}
        audit_settings = load_audit_settings() if run_audit else None
        for path in files:
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXTS:
                skipped += 1
                continue
            try:
                if run_audit and audit_settings is not None:
                    audit = evaluate_audit_settings(path, audit_settings)
                    if not audit["pass"]:
                        skipped += 1
                        continue
                meta = extract_track_meta(path)
                if is_duplicate_of_registered(meta, registered, seen_in_batch=seen_identities):
                    duplicate_skipped += 1
                    print(
                        f"[library] duplicate skip register {meta.get('file_path')} "
                        f"({meta.get('artist')} — {meta.get('title')})"
                    )
                    continue
                verdict = evaluate_hires(path)
                meta["quality"] = verdict.get("tier", "unknown")
                meta["quality_reasons"] = json.dumps(verdict.get("reasons") or [])
                meta["storage_source"] = _storage_source_for_path(path)
                await upsert_track(conn, meta)
                ident = track_identity_key(meta.get("artist"), meta.get("title"))
                if ident:
                    seen_identities[ident] = meta["file_path"]
                    registered[ident] = meta["file_path"]
                upserted += 1
            except Exception as exc:
                print(f"[library] register skip {path}: {exc}")
                skipped += 1
        total = int(await conn.fetchval("SELECT COUNT(*) FROM tracks") or 0)
    return {
        "ok": True,
        "upserted": upserted,
        "skipped": skipped,
        "duplicate_skipped": duplicate_skipped,
        "total_tracks": total,
    }


async def delete_tracks_by_file_paths(pool: asyncpg.Pool, file_paths: list[str]) -> int:
    if not file_paths:
        return 0
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT track_id FROM tracks WHERE file_path = ANY($1::text[])",
            file_paths,
        )
        ids = [r["track_id"] for r in rows]
        if not ids:
            return 0
        await conn.execute("DELETE FROM play_history WHERE track_id = ANY($1::bigint[])", ids)
        await conn.execute("DELETE FROM favorites WHERE track_id = ANY($1::bigint[])", ids)
        await conn.execute("DELETE FROM playlist_tracks WHERE track_id = ANY($1::bigint[])", ids)
        await conn.execute("DELETE FROM tracks WHERE track_id = ANY($1::bigint[])", ids)
        return len(ids)


async def delete_tracks_by_ids(
    pool: asyncpg.Pool, track_ids: list[int]
) -> tuple[int, list[str]]:
    """track_id 목록으로 DB 행 삭제. (file_path 목록도 함께 반환 — 파일 삭제용)"""
    ids = sorted({int(x) for x in track_ids if int(x) > 0})
    if not ids:
        return 0, []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT track_id, file_path FROM tracks WHERE track_id = ANY($1::bigint[])",
            ids,
        )
        paths = [str(r["file_path"]) for r in rows if r.get("file_path")]
        found = [int(r["track_id"]) for r in rows]
        if not found:
            return 0, []
        await conn.execute("DELETE FROM play_history WHERE track_id = ANY($1::bigint[])", found)
        await conn.execute("DELETE FROM favorites WHERE track_id = ANY($1::bigint[])", found)
        await conn.execute("DELETE FROM playlist_tracks WHERE track_id = ANY($1::bigint[])", found)
        await conn.execute("DELETE FROM tracks WHERE track_id = ANY($1::bigint[])", found)
        return len(found), paths


def _file_path_prefix_variants(prefix: str) -> list[str]:
    """내폴더 삭제 경로 ↔ DB file_path 매칭용 변형 (/media ↔ /run/media/<user>)."""
    raw = str(prefix or "").strip().rstrip("/")
    if not raw:
        return []
    out: set[str] = {raw}
    try:
        out.add(str(Path(raw).resolve()))
    except OSError:
        pass
    if raw.startswith("/media/"):
        rest = raw[len("/media/") :]
        run = Path("/run/media")
        if run.is_dir():
            try:
                for user_dir in run.iterdir():
                    if user_dir.is_dir():
                        out.add(str(user_dir / rest))
                        try:
                            out.add(str((user_dir / rest).resolve()))
                        except OSError:
                            pass
            except OSError:
                pass
    elif raw.startswith("/run/media/"):
        parts = [p for p in raw.split("/") if p]
        # run, media, <user>, <label>, ...
        if len(parts) >= 4:
            rest = "/".join(parts[3:])
            out.add(f"/media/{rest}")
            try:
                out.add(str(Path(f"/media/{rest}").resolve()))
            except OSError:
                pass
    return [p for p in out if p]


async def delete_tracks_under_prefixes(pool: asyncpg.Pool, prefixes: list[str]) -> int:
    """삭제된 폴더/파일 접두사에 해당하는 라이브러리(바로가기) 트랙 제거."""
    if not prefixes:
        return 0
    variants: list[str] = []
    seen: set[str] = set()
    for prefix in prefixes:
        for v in _file_path_prefix_variants(prefix):
            if v not in seen:
                seen.add(v)
                variants.append(v)
    if not variants:
        return 0
    async with pool.acquire() as conn:
        ids: list[int] = []
        for p in variants:
            rows = await conn.fetch(
                "SELECT track_id FROM tracks WHERE file_path = $1 OR file_path LIKE $2",
                p,
                p + "/%",
            )
            ids.extend(r["track_id"] for r in rows)
        ids = sorted(set(ids))
        if not ids:
            return 0
        await conn.execute("DELETE FROM play_history WHERE track_id = ANY($1::bigint[])", ids)
        await conn.execute("DELETE FROM favorites WHERE track_id = ANY($1::bigint[])", ids)
        await conn.execute("DELETE FROM playlist_tracks WHERE track_id = ANY($1::bigint[])", ids)
        await conn.execute("DELETE FROM tracks WHERE track_id = ANY($1::bigint[])", ids)
        return len(ids)


async def remap_track_paths(pool: asyncpg.Pool, old_prefix: str, new_prefix: str) -> int:
    """rename/move 후 file_path 접두사 치환."""
    old_p = str(old_prefix).rstrip("/")
    new_p = str(new_prefix).rstrip("/")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT track_id, file_path FROM tracks WHERE file_path = $1 OR file_path LIKE $2",
            old_p,
            old_p + "/%",
        )
        n = 0
        for row in rows:
            fp = row["file_path"]
            if fp == old_p:
                new_fp = new_p
            elif fp.startswith(old_p + "/"):
                new_fp = new_p + fp[len(old_p) :]
            else:
                continue
            src = "external" if new_fp.startswith("/media/") or new_fp.startswith("/run/media/") else "internal"
            try:
                await conn.execute(
                    "UPDATE tracks SET file_path = $1, storage_source = $2 WHERE track_id = $3",
                    new_fp,
                    src,
                    row["track_id"],
                )
                n += 1
            except Exception as exc:
                print(f"[library] remap skip {fp}: {exc}")
        return n

