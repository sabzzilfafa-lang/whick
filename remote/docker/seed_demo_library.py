#!/usr/bin/env python3
"""PoC 데모 라이브러리 — 무음 WAV 3곡 + PostgreSQL 메타."""
from __future__ import annotations

import asyncio
import os
import struct
import wave
from pathlib import Path

import asyncpg

DATABASE_URL = os.environ["DATABASE_URL"]
MUSIC_DIR = Path(os.environ.get("WHICK_MUSIC_DIR", "/var/lib/whick/library/music"))
DEMO_DIR = MUSIC_DIR / "demo"

DEMO_TRACKS = [
    {
        "title": "Clair de Lune",
        "artist": "Debussy",
        "album": "Suite Bergamasque",
        "genre": "Classical",
        "year": 1905,
        "duration_sec": 3,
        "bit_depth": 16,
        "sample_rate": 44100,
        "format": "WAV",
        "filename": "clair_de_lune.wav",
    },
    {
        "title": "Moonlight Sonata",
        "artist": "Beethoven",
        "album": "Piano Sonata No. 14",
        "genre": "Classical",
        "year": 1801,
        "duration_sec": 3,
        "bit_depth": 16,
        "sample_rate": 44100,
        "format": "WAV",
        "filename": "moonlight.wav",
    },
    {
        "title": "Spring",
        "artist": "Vivaldi",
        "album": "The Four Seasons",
        "genre": "Classical",
        "year": 1725,
        "duration_sec": 3,
        "bit_depth": 16,
        "sample_rate": 44100,
        "format": "WAV",
        "filename": "spring.wav",
    },
]


def write_silent_wav(path: Path, duration_sec: int = 3, sample_rate: int = 44100) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    nframes = duration_sec * sample_rate
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        silence = struct.pack("<h", 0)
        wf.writeframes(silence * 2 * nframes)
    return path.stat().st_size


async def main() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM tracks")
        if count and int(count) > 0:
            print(f"[seed] library already has {count} tracks — skip")
            return

        DEMO_DIR.mkdir(parents=True, exist_ok=True)
        for track in DEMO_TRACKS:
            fpath = DEMO_DIR / track["filename"]
            size = write_silent_wav(fpath, track["duration_sec"], track["sample_rate"])
            await conn.execute(
                """
                INSERT INTO tracks
                  (title, artist, album, genre, year, duration_sec,
                   bit_depth, sample_rate, format, file_path, file_size, license)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                ON CONFLICT (file_path) DO NOTHING
                """,
                track["title"],
                track["artist"],
                track["album"],
                track["genre"],
                track["year"],
                track["duration_sec"],
                track["bit_depth"],
                track["sample_rate"],
                track["format"],
                str(fpath),
                size,
                "Demo",
            )
        total = await conn.fetchval("SELECT COUNT(*) FROM tracks")
        print(f"[seed] demo library ready — {total} tracks in {DEMO_DIR}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
