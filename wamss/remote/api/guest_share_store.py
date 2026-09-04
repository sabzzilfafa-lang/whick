"""게스트 추천곡 공유 — 24h 토큰 · 허용 트랙만 스트리밍."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

SHARE_TTL_DEFAULT_SEC = 24 * 3600


def hash_guest_token(guest_token: str) -> str:
    return hashlib.sha256(guest_token.encode("utf-8")).hexdigest()


async def ensure_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS guest_shares (
                token_hash   TEXT PRIMARY KEY,
                title        VARCHAR(200),
                track_ids    BIGINT[] NOT NULL DEFAULT '{}',
                created_at   TIMESTAMPTZ DEFAULT now(),
                expires_at   TIMESTAMPTZ NOT NULL,
                revoked_at   TIMESTAMPTZ,
                play_count   INT DEFAULT 0
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_guest_shares_expires ON guest_shares(expires_at)"
        )


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def create_share(
    pool: asyncpg.Pool,
    *,
    guest_token: str,
    title: str,
    track_ids: list[int],
    expires_at: datetime | None = None,
    expires_in_sec: int | None = None,
) -> dict[str, Any]:
    await ensure_schema(pool)
    gt = (guest_token or "").strip()
    if len(gt) < 8:
        raise ValueError("guest_token too short")
    ids = sorted({int(x) for x in track_ids if x is not None})
    if not ids:
        raise ValueError("track_ids empty")

    if expires_at is None:
        sec = expires_in_sec or SHARE_TTL_DEFAULT_SEC
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=sec)
    else:
        expires_at = _utc(expires_at)

    th = hash_guest_token(gt)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO guest_shares (token_hash, title, track_ids, expires_at, revoked_at)
            VALUES ($1, $2, $3, $4, NULL)
            ON CONFLICT (token_hash) DO UPDATE SET
              title = EXCLUDED.title,
              track_ids = EXCLUDED.track_ids,
              expires_at = EXCLUDED.expires_at,
              revoked_at = NULL
            """,
            th,
            (title or "").strip() or "추천곡",
            ids,
            expires_at,
        )
    return {
        "ok": True,
        "expires_at": expires_at.isoformat(),
        "track_count": len(ids),
    }


async def _fetch_share(pool: asyncpg.Pool, guest_token: str) -> asyncpg.Record | None:
    await ensure_schema(pool)
    th = hash_guest_token(guest_token.strip())
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT token_hash, title, track_ids, expires_at, revoked_at, play_count
            FROM guest_shares WHERE token_hash = $1
            """,
            th,
        )


def _share_active(row: asyncpg.Record | None) -> bool:
    if not row:
        return False
    if row["revoked_at"]:
        return False
    exp = row["expires_at"]
    if exp:
        exp = _utc(exp)
        if datetime.now(timezone.utc) > exp:
            return False
    return True


async def verify_guest_token(pool: asyncpg.Pool, guest_token: str, track_id: int) -> bool:
    if not guest_token or not pool:
        return False
    row = await _fetch_share(pool, guest_token)
    if not _share_active(row):
        return False
    allowed = row["track_ids"] or []
    return int(track_id) in allowed


async def revoke_share(pool: asyncpg.Pool, guest_token: str) -> bool:
    if not guest_token:
        return False
    await ensure_schema(pool)
    th = hash_guest_token(guest_token.strip())
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE guest_shares SET revoked_at = now() WHERE token_hash = $1 AND revoked_at IS NULL",
            th,
        )
    return result.endswith("1")


async def resolve_share(pool: asyncpg.Pool, guest_token: str) -> dict[str, Any] | None:
    """게스트용 — 허용 트랙 메타 (로그인·device_token 불필요)."""
    row = await _fetch_share(pool, guest_token)
    if not _share_active(row):
        return None
    ids = list(row["track_ids"] or [])
    if not ids:
        return None
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT track_id, title, artist, album, duration_sec,
                   bit_depth, sample_rate, format
            FROM tracks WHERE track_id = ANY($1::bigint[])
            ORDER BY array_position($1::bigint[], track_id)
            """,
            ids,
        )
    tracks = []
    for r in rows:
        bd = r.get("bit_depth") or 16
        sr = r.get("sample_rate") or 44100
        sr_k = sr // 1000 if sr >= 1000 else sr
        fmt = r.get("format") or "FLAC"
        tracks.append(
            {
                "track_id": r["track_id"],
                "title": r["title"],
                "artist": r["artist"],
                "album": r["album"],
                "duration_sec": r["duration_sec"],
                "quality": f"{bd}/{sr_k} {fmt}",
            }
        )
    exp = row["expires_at"]
    return {
        "title": row["title"],
        "expires_at": _utc(exp).isoformat() if exp else None,
        "tracks": tracks,
    }


async def cleanup_expired(pool: asyncpg.Pool) -> int:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM guest_shares WHERE expires_at < now() - interval '7 days'"
        )
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0
