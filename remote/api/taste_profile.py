"""개인 취향 프로필 · 미재생 유사곡 후보 (미니PC AI DJ)."""
from __future__ import annotations

from typing import Any


async def build_taste_profile(conn) -> dict[str, Any]:
    """play_history + favorites + play_count → 취향 프로필."""
    artist_rows = await conn.fetch(
        """
        SELECT t.artist, COUNT(*) AS cnt
        FROM play_history h
        JOIN tracks t ON t.track_id = h.track_id
        WHERE h.played_at > now() - interval '90 days'
          AND COALESCE(t.artist, '') <> ''
        GROUP BY t.artist
        ORDER BY cnt DESC, t.artist ASC
        LIMIT 8
        """
    )
    genre_rows = await conn.fetch(
        """
        SELECT t.genre, COUNT(*) AS cnt
        FROM play_history h
        JOIN tracks t ON t.track_id = h.track_id
        WHERE h.played_at > now() - interval '90 days'
          AND COALESCE(t.genre, '') <> ''
        GROUP BY t.genre
        ORDER BY cnt DESC, t.genre ASC
        LIMIT 6
        """
    )
    played_rows = await conn.fetch(
        """
        SELECT DISTINCT track_id
        FROM play_history
        WHERE played_at > now() - interval '180 days'
        """
    )
    fav_rows = await conn.fetch(
        """
        SELECT t.track_id, t.title, t.artist, t.genre
        FROM favorites f
        JOIN tracks t ON t.track_id = f.track_id
        ORDER BY f.added_at DESC
        LIMIT 10
        """
    )
    top_played = await conn.fetch(
        """
        SELECT t.track_id, t.title, t.artist, t.genre, t.play_count
        FROM tracks t
        WHERE t.play_count > 0
        ORDER BY t.play_count DESC, t.last_played DESC NULLS LAST
        LIMIT 10
        """
    )
    weather_rows = await conn.fetch(
        """
        SELECT weather, COUNT(*) AS cnt
        FROM play_history
        WHERE played_at > now() - interval '90 days'
          AND COALESCE(weather, '') <> ''
        GROUP BY weather
        ORDER BY cnt DESC
        LIMIT 4
        """
    )
    period_rows = await conn.fetch(
        """
        SELECT period, COUNT(*) AS cnt
        FROM play_history
        WHERE played_at > now() - interval '90 days'
          AND COALESCE(period, '') <> ''
        GROUP BY period
        ORDER BY cnt DESC
        LIMIT 4
        """
    )

    top_artists = [str(r["artist"]) for r in artist_rows if r.get("artist")]
    top_genres = [str(r["genre"]) for r in genre_rows if r.get("genre")]
    top_weather = [str(r["weather"]) for r in weather_rows if r.get("weather")]
    top_periods = [str(r["period"]) for r in period_rows if r.get("period")]
    played_ids = {int(r["track_id"]) for r in played_rows}
    for r in top_played:
        played_ids.add(int(r["track_id"]))

    has_data = bool(top_artists or top_genres or top_played or fav_rows or top_weather)
    return {
        "has_data": has_data,
        "top_artists": top_artists,
        "top_genres": top_genres,
        "top_weather": top_weather,
        "top_periods": top_periods,
        "played_track_ids": sorted(played_ids),
        "favorites": [dict(r) for r in fav_rows],
        "top_played": [dict(r) for r in top_played],
    }


async def fetch_recommend_candidates(
    conn,
    profile: dict[str, Any],
    limit: int = 50,
) -> list[dict[str, Any]]:
    """미재생 + 취향 유사 후보."""
    lim = max(10, min(int(limit or 50), 80))
    played = profile.get("played_track_ids") or []
    artists = profile.get("top_artists") or []
    genres = profile.get("top_genres") or []

    if not played and not artists and not genres:
        rows = await conn.fetch(
            """
            SELECT track_id, title, artist, album, genre, duration_sec,
                   bit_depth, sample_rate, format, play_count
            FROM tracks
            ORDER BY bit_depth DESC NULLS LAST, sample_rate DESC NULLS LAST, title ASC
            LIMIT $1
            """,
            lim,
        )
        return [dict(r) for r in rows]

    rows = await conn.fetch(
        """
        SELECT track_id, title, artist, album, genre, duration_sec,
               bit_depth, sample_rate, format, play_count
        FROM tracks t
        WHERE (
            CARDINALITY($1::bigint[]) = 0 OR t.track_id <> ALL($1::bigint[])
        )
        AND (
            ($2::text[] <> '{}' AND t.artist = ANY($2::text[]))
            OR ($3::text[] <> '{}' AND t.genre = ANY($3::text[]))
            OR t.play_count = 0
        )
        ORDER BY
            CASE WHEN $2::text[] <> '{}' AND t.artist = ANY($2::text[]) THEN 0 ELSE 1 END,
            CASE WHEN $3::text[] <> '{}' AND t.genre = ANY($3::text[]) THEN 0 ELSE 1 END,
            t.play_count ASC,
            t.bit_depth DESC NULLS LAST,
            t.sample_rate DESC NULLS LAST
        LIMIT $4
        """,
        played,
        artists,
        genres,
        lim,
    )
    candidates = [dict(r) for r in rows]

    if len(candidates) < min(lim, 10):
        extra = await conn.fetch(
            """
            SELECT track_id, title, artist, album, genre, duration_sec,
                   bit_depth, sample_rate, format, play_count
            FROM tracks t
            WHERE CARDINALITY($1::bigint[]) = 0 OR t.track_id <> ALL($1::bigint[])
            ORDER BY t.play_count ASC, t.bit_depth DESC NULLS LAST
            LIMIT $2
            """,
            played,
            lim - len(candidates),
        )
        seen = {c["track_id"] for c in candidates}
        for r in extra:
            if r["track_id"] not in seen:
                candidates.append(dict(r))
                seen.add(r["track_id"])

    return candidates[:lim]


def profile_summary(
    profile: dict[str, Any],
    live_context: dict[str, Any] | None = None,
    lang: str | None = None,
) -> str:
    # ko가 아닌 모든 언어는 영어 요약 (파파 지시 2026-08-17)
    is_en = lang is not None and lang != "ko"
    parts = []
    live = live_context or {}
    if live.get("weather") or live.get("period"):
        loc = live.get("location_label") or ""
        bits = [x for x in (loc, live.get("weather"), live.get("period"), live.get("mood")) if x]
        if bits:
            parts.append(("Current: " if is_en else "현재 상황: ") + " · ".join(bits))
    if not profile.get("has_data") and not parts:
        return "No listening history — recommend from full library" if is_en else "청취 기록 없음 — 라이브러리 전체에서 추천"
    if profile.get("top_artists"):
        parts.append(("Preferred artists: " if is_en else "선호 아티스트: ") + ", ".join(profile["top_artists"][:4]))
    if profile.get("top_genres"):
        parts.append(("Preferred genres: " if is_en else "선호 장르: ") + ", ".join(profile["top_genres"][:3]))
    if profile.get("top_weather"):
        parts.append(("Frequent weather: " if is_en else "자주 듣는 날씨: ") + ", ".join(profile["top_weather"][:2]))
    if profile.get("top_periods"):
        parts.append(("Frequent times: " if is_en else "자주 듣는 시간대: ") + ", ".join(profile["top_periods"][:2]))
    unplayed = len([t for t in profile.get("top_played") or [] if t.get("play_count", 0) == 0])
    if unplayed:
        parts.append(f"{unplayed}+ unexplored tracks" if is_en else f"미탐색 후보 {unplayed}곡+")
    return " · ".join(parts) if parts else ("Personal taste profile" if is_en else "개인 취향 프로필")


def streaming_search_query(profile: dict[str, Any]) -> str:
    """Spotify/Tidal federated 검색용 쿼리."""
    if profile.get("top_artists"):
        artist = profile["top_artists"][0]
        genre = (profile.get("top_genres") or [""])[0]
        return f"{artist} {genre}".strip()
    if profile.get("top_genres"):
        return profile["top_genres"][0]
    return "relax instrumental"
