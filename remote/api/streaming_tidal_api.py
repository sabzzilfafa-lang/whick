"""Tidal catalog 검색 · 스트림 URL — device flow 토큰 (계정 지역 countryCode)."""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx

from api import streaming_tidal_tokens as tt

V1_BASE = "https://api.tidal.com/v1"


def _lab_mode() -> bool:
    return os.getenv("WHICK_STREAMING_LAB", "0") == "1"


def _track_from_v1_item(item: dict[str, Any]) -> dict[str, Any]:
    artist = ""
    if item.get("artists"):
        artist = str(item["artists"][0].get("name") or "")
    album = item.get("album") or {}
    return {
        "stream_id": str(item.get("id") or ""),
        "title": str(item.get("title") or ""),
        "artist": artist,
        "album": str(album.get("title") or ""),
        "duration_sec": int(item.get("duration") or 0),
    }


def _parse_v2_search(data: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    included = {
        f"{x.get('type')}:{x.get('id')}": x
        for x in data.get("included") or []
        if x.get("id")
    }
    out: list[dict[str, Any]] = []

    def append_track(tr: dict[str, Any]) -> None:
        if len(out) >= limit:
            return
        attrs = tr.get("attributes") or {}
        if not attrs.get("title"):
            return
        artist = attrs.get("artistName") or ""
        if not artist and isinstance(attrs.get("artist"), dict):
            artist = str(attrs["artist"].get("name") or "")
        album = attrs.get("albumTitle") or ""
        if not album and isinstance(attrs.get("album"), dict):
            album = str(attrs["album"].get("title") or "")
        out.append(
            {
                "stream_id": str(tr.get("id") or ""),
                "title": str(attrs.get("title") or ""),
                "artist": str(artist),
                "album": str(album),
                "duration_sec": int(attrs.get("duration") or 0),
            }
        )

    root = data.get("data")
    if isinstance(root, dict):
        rel = (root.get("relationships") or {}).get("tracks") or {}
        for ref in rel.get("data") or []:
            key = f"{ref.get('type')}:{ref.get('id')}"
            tr = included.get(key) or {}
            if tr:
                append_track(tr)
    for tr in included.values():
        if tr.get("type") != "tracks":
            continue
        append_track(tr)
        if len(out) >= limit:
            break
    return out


async def search_tracks(q: str, limit: int = 8) -> tuple[list[dict[str, Any]], str | None]:
    """Returns (tracks, error). tracks empty + error set on failure."""
    token = await tt.valid_access_token()
    if tt.is_lab_token(token):
        return [], None if _lab_mode() else "tidal not connected"

    country = tt.country_code()
    async with httpx.AsyncClient(timeout=20) as client:
        v2 = await client.get(
            f"{tt.TIDAL_OPENAPI}/v2/searchResults/{quote(q, safe='')}",
            headers=tt.openapi_headers(str(token)),
            params={"countryCode": country, "include": "tracks"},
        )
        if v2.status_code < 400:
            parsed = _parse_v2_search(v2.json(), limit)
            if parsed:
                return parsed, None

        v1 = await client.get(
            f"{V1_BASE}/search",
            headers=tt.v1_headers(str(token)),
            params={
                "query": q,
                "limit": limit,
                "offset": 0,
                "types": "TRACKS",
                "countryCode": country,
            },
        )
        if v1.status_code >= 400:
            return [], f"tidal search failed ({v1.status_code})"
        items = (v1.json().get("tracks") or {}).get("items") or []
        return [_track_from_v1_item(item) for item in items[:limit]], None


def _pick_stream_url(payload: dict[str, Any]) -> str:
    url = str(payload.get("url") or "")
    if url.startswith("http"):
        return url
    for entry in payload.get("urls") or []:
        if isinstance(entry, dict):
            u = str(entry.get("url") or "")
            if u.startswith("http"):
                return u
    return ""


def _manifest_http_url(payload: dict[str, Any]) -> str:
    node = payload.get("data") or payload
    if isinstance(node, list) and node:
        node = node[0]
    attrs = (node or {}).get("attributes") or {}
    for key in ("manifestUri", "uri", "url"):
        val = attrs.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    for entry in attrs.get("urls") or []:
        if isinstance(entry, dict):
            u = str(entry.get("url") or "")
            if u.startswith("http"):
                return u
    return ""


async def resolve_playback_url(track_id: str) -> tuple[str | None, str | None]:
    """MPD에 넣을 HTTP URL. (url, error)"""
    token = await tt.valid_access_token()
    if tt.is_lab_token(token):
        if _lab_mode():
            return os.getenv(
                "WHICK_STREAMING_LAB_URL",
                "http://stream.kbs.co.kr:8000/kbs1radio",
            ), None
        return None, "tidal not connected"

    country = tt.country_code()
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        headers = tt.v1_headers(str(token))
        for path in (f"/tracks/{track_id}/streamUrl", f"/tracks/{track_id}/urlpostpaywall"):
            resp = await client.get(
                f"{V1_BASE}{path}",
                params={"soundQuality": "LOSSLESS", "countryCode": country},
                headers=headers,
            )
            if resp.status_code < 400:
                url = _pick_stream_url(resp.json())
                if url:
                    return url, None

        manifest = await client.get(
            f"{tt.TIDAL_OPENAPI}/v2/trackManifests/{track_id}",
            params={
                "countryCode": country,
                "formats": "FLAC",
                "manifestType": "MPEG_DASH",
                "uriScheme": "HTTPS",
                "usage": "PLAYBACK",
            },
            headers=tt.openapi_headers(str(token)),
        )
        if manifest.status_code < 400:
            url = _manifest_http_url(manifest.json())
            if url:
                return url, None
        return None, f"tidal stream unavailable ({manifest.status_code})"
