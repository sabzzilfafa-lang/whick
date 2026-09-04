"""사용자 플레이리스트 — 체험 whick-trial-player favorites store 대응."""
from __future__ import annotations

from typing import Any

import asyncpg


async def ensure_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS playlists (
                playlist_id BIGSERIAL PRIMARY KEY,
                name        VARCHAR(200) NOT NULL,
                created_at  TIMESTAMPTZ DEFAULT now(),
                updated_at  TIMESTAMPTZ DEFAULT now()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS playlist_tracks (
                playlist_id BIGINT REFERENCES playlists(playlist_id) ON DELETE CASCADE,
                track_id    BIGINT REFERENCES tracks(track_id) ON DELETE CASCADE,
                position    INT NOT NULL DEFAULT 0,
                added_at    TIMESTAMPTZ DEFAULT now(),
                PRIMARY KEY (playlist_id, track_id)
            )
            """
        )


async def list_playlists(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.playlist_id, p.name, p.updated_at,
                   COUNT(pt.track_id)::int AS track_count
            FROM playlists p
            LEFT JOIN playlist_tracks pt ON pt.playlist_id = p.playlist_id
            GROUP BY p.playlist_id, p.name, p.updated_at
            ORDER BY p.updated_at DESC
            """
        )
    return [dict(r) for r in rows]


async def create_playlist(pool: asyncpg.Pool, name: str) -> dict[str, Any]:
    await ensure_schema(pool)
    name = (name or "").strip() or "새 플레이리스트"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playlists (name) VALUES ($1)
            RETURNING playlist_id, name, created_at, updated_at
            """,
            name,
        )
    return {**dict(row), "track_count": 0}


async def get_playlist_tracks(pool: asyncpg.Pool, playlist_id: int) -> list[dict[str, Any]]:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.track_id, t.title, t.artist, t.album, t.duration_sec,
                   t.bit_depth, t.sample_rate, t.format, pt.position
            FROM playlist_tracks pt
            JOIN tracks t ON t.track_id = pt.track_id
            WHERE pt.playlist_id = $1
            ORDER BY pt.position, pt.added_at
            """,
            playlist_id,
        )
    return [dict(r) for r in rows]


async def add_track(pool: asyncpg.Pool, playlist_id: int, track_id: int) -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        pos = await conn.fetchval(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM playlist_tracks WHERE playlist_id = $1",
            playlist_id,
        )
        await conn.execute(
            """
            INSERT INTO playlist_tracks (playlist_id, track_id, position)
            VALUES ($1, $2, $3)
            ON CONFLICT (playlist_id, track_id) DO NOTHING
            """,
            playlist_id,
            track_id,
            pos,
        )
        await conn.execute(
            "UPDATE playlists SET updated_at = now() WHERE playlist_id = $1",
            playlist_id,
        )


async def remove_track(pool: asyncpg.Pool, playlist_id: int, track_id: int) -> bool:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playlist_tracks WHERE playlist_id = $1 AND track_id = $2",
            playlist_id,
            track_id,
        )
        if result.endswith("1"):
            await conn.execute(
                "UPDATE playlists SET updated_at = now() WHERE playlist_id = $1",
                playlist_id,
            )
            return True
        return False


async def delete_playlist(pool: asyncpg.Pool, playlist_id: int) -> bool:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM playlists WHERE playlist_id = $1", playlist_id)
    return result.endswith("1")
