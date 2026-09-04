"""Spotify · Tidal 검색·재생 — Whick 리모컨 통합."""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Literal

import httpx

from api import streaming_providers

ProviderId = Literal["spotify", "tidal"]

SPOTIFY_CREDS = streaming_providers.PROVIDERS_DIR / "spotify-credentials.json"
SPOTIFY_API = "https://api.spotify.com/v1"
SPOTIFY_DEVICE_NAME = streaming_providers.SPOTIFY_DEVICE_NAME
LAB_STREAM_URL = os.getenv(
    "WHICK_STREAMING_LAB_URL",
    "http://stream.kbs.co.kr:8000/kbs1radio",
)


def _load_json(path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _provider_connected(provider: ProviderId) -> bool:
    st = streaming_providers.get_streaming_status()
    return st.get("providers", {}).get(provider, {}).get("status") == "connected"


def _lab_mode() -> bool:
    return os.getenv("WHICK_STREAMING_LAB", "0") == "1"


def track_shape(
    *,
    provider: ProviderId,
    stream_id: str,
    title: str,
    artist: str,
    album: str = "",
    duration_sec: int = 0,
    quality: str = "",
    uri: str = "",
) -> dict[str, Any]:
    return {
        "source": provider,
        "stream_id": stream_id,
        "track_id": None,
        "title": title,
        "artist": artist,
        "album": album,
        "duration_sec": duration_sec,
        "quality": quality or ("320/Ogg" if provider == "spotify" else "HiFi/FLAC"),
        "uri": uri or stream_id,
    }


def _lab_spotify_results(q: str) -> list[dict[str, Any]]:
    seed = abs(hash(q)) % 900 + 100
    return [
        track_shape(
            provider="spotify",
            stream_id=f"spotify:track:lab{seed}",
            title=f"{q} — Spotify 결과 {i + 1}",
            artist="Spotify (lab)",
            album="Whick Streaming Demo",
            duration_sec=210 + i * 15,
        )
        for i in range(3)
    ]


def _lab_tidal_results(q: str) -> list[dict[str, Any]]:
    seed = abs(hash(q + "tidal")) % 900 + 100
    return [
        track_shape(
            provider="tidal",
            stream_id=str(seed * 10 + i),
            title=f"{q} — Tidal 결과 {i + 1}",
            artist="Tidal (lab)",
            album="Whick Streaming Demo",
            duration_sec=240 + i * 12,
            quality="HiFi/FLAC",
        )
        for i in range(3)
    ]


async def _spotify_access_token() -> str | None:
    creds = _load_json(SPOTIFY_CREDS)
    token = str(creds.get("access_token") or "")
    if token == "lab-access-token":
        return token if _lab_mode() else None
    if token:
        from api import streaming_spotify_oauth

        if streaming_spotify_oauth.oauth_configured():
            refreshed = await streaming_spotify_oauth.refresh_access_token()
            if refreshed:
                return refreshed
        return token
    return None


async def _spotify_api(method: str, path: str, **kwargs) -> dict[str, Any] | None:
    token = await _spotify_access_token()
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.request(method, f"{SPOTIFY_API}{path}", headers=headers, **kwargs)
        if resp.status_code == 401:
            return None
        if resp.status_code >= 400:
            return None
        if resp.content:
            return resp.json()
        return {}


async def _spotify_device_id() -> str | None:
    env_id = os.getenv("WHICK_SPOTIFY_DEVICE_ID", "").strip()
    if env_id:
        return env_id
    data = await _spotify_api("GET", "/me/player/devices")
    if not data:
        return None
    for dev in data.get("devices") or []:
        if dev.get("name") == SPOTIFY_DEVICE_NAME and dev.get("id"):
            return str(dev["id"])
    for dev in data.get("devices") or []:
        if dev.get("is_active") and dev.get("id"):
            return str(dev["id"])
    return None


async def search_spotify(q: str, limit: int = 8) -> list[dict[str, Any]]:
    if not _provider_connected("spotify"):
        return []
    data = await _spotify_api(
        "GET",
        "/search",
        params={"q": q, "type": "track", "limit": limit},
    )
    if not data:
        if _lab_mode():
            return _lab_spotify_results(q)
        return []
    out: list[dict[str, Any]] = []
    for item in (data.get("tracks") or {}).get("items") or []:
        artists = ", ".join(a.get("name", "") for a in item.get("artists") or [])
        album = (item.get("album") or {}).get("name") or ""
        out.append(
            track_shape(
                provider="spotify",
                stream_id=str(item.get("uri") or item.get("id") or ""),
                title=str(item.get("name") or ""),
                artist=artists,
                album=album,
                duration_sec=int((item.get("duration_ms") or 0) // 1000),
                uri=str(item.get("uri") or ""),
            )
        )
    return out


async def search_tidal(q: str, limit: int = 8) -> list[dict[str, Any]]:
    if not _provider_connected("tidal"):
        return []
    from api import streaming_tidal_api, streaming_tidal_tokens

    token = await streaming_tidal_tokens.valid_access_token()
    if streaming_tidal_tokens.is_lab_token(token):
        return _lab_tidal_results(q) if _lab_mode() else []

    tracks, err = await streaming_tidal_api.search_tracks(q, limit)
    if tracks:
        return [
            track_shape(
                provider="tidal",
                stream_id=t["stream_id"],
                title=t["title"],
                artist=t["artist"],
                album=t["album"],
                duration_sec=t["duration_sec"],
            )
            for t in tracks
        ]
    if err and _lab_mode():
        return _lab_tidal_results(q)
    return []


async def federated_search(q: str, providers: list[str] | None = None) -> dict[str, Any]:
    want = {p.strip().lower() for p in (providers or ["spotify", "tidal"]) if p}
    result: dict[str, Any] = {"query": q, "spotify": [], "tidal": []}
    if "spotify" in want:
        result["spotify"] = await search_spotify(q)
    if "tidal" in want:
        result["tidal"] = await search_tidal(q)
    merged: list[dict[str, Any]] = []
    for p in ("spotify", "tidal"):
        for tr in result.get(p) or []:
            merged.append(tr)
    result["tracks"] = merged
    return result


def _mpd_play_url(url: str) -> None:
    try:
        subprocess.run(["mpc", "--quiet", "clear"], timeout=5, capture_output=True, check=False)
        subprocess.run(["mpc", "--quiet", "add", url], timeout=5, capture_output=True, check=False)
        subprocess.run(["mpc", "--quiet", "play"], timeout=5, capture_output=True, check=False)
    except Exception as exc:
        print(f"[streaming] mpd play url → {exc}")


def _mpd_cmd(command: str) -> None:
    try:
        subprocess.run(
            ["mpc", "--quiet", *command.split()],
            timeout=3,
            capture_output=True,
            check=False,
        )
    except Exception as exc:
        print(f"[streaming] mpd {command} → {exc}")


async def play_spotify(
    stream_id: str,
    *,
    queue: list[dict[str, Any]] | None = None,
    mpd_play: bool = True,
) -> dict[str, Any]:
    if not mpd_play:
        return {"ok": True, "path": "mobile-client", "lab": False}

    uris = [stream_id]
    if queue:
        uris = [str(t.get("uri") or t.get("stream_id") or "") for t in queue if t.get("stream_id")]
        if stream_id not in uris:
            uris.insert(0, stream_id)

    streaming_providers._start_librespot_zeroconf()
    device_id = await _spotify_device_id()
    body: dict[str, Any] = {"uris": uris}
    if device_id:
        body["device_id"] = device_id

    ok = False
    path = "none"
    if await _spotify_access_token() and device_id:
        data = await _spotify_api("PUT", "/me/player/play", json=body)
        ok = data is not None
        if ok:
            path = "librespot-camilla"
            streaming_providers._start_librespot_zeroconf()

    if not ok and _lab_mode() and mpd_play:
        streaming_providers._start_librespot_zeroconf()
        _mpd_play_url(LAB_STREAM_URL)
        ok = True
        path = "mpd-lab"

    return {"ok": ok, "device_id": device_id, "lab": path == "mpd-lab", "path": path}


async def _tidal_stream_url(track_id: str) -> tuple[str | None, str | None]:
    from api import streaming_tidal_api

    return await streaming_tidal_api.resolve_playback_url(track_id)


async def play_tidal(
    stream_id: str,
    *,
    queue: list[dict[str, Any]] | None = None,
    mpd_play: bool = True,
) -> dict[str, Any]:
    url, err = await _tidal_stream_url(stream_id)
    lab_url = os.getenv("WHICK_STREAMING_LAB_URL", "http://stream.kbs.co.kr:8000/kbs1radio")
    if url and mpd_play:
        _mpd_play_url(url)
        return {"ok": True, "stream_url": url, "lab": url == lab_url, "path": "mpd-camilla"}
    if url and not mpd_play:
        return {"ok": True, "stream_url": url, "lab": url == lab_url, "path": "mobile-client"}
    return {"ok": False, "error": err or "tidal stream unavailable", "path": "none"}


def _spotify_track_id(stream_id: str) -> str:
    sid = str(stream_id or "")
    if sid.startswith("spotify:track:"):
        return sid.split(":")[-1]
    return sid


async def get_mobile_playback_url(provider: ProviderId, stream_id: str) -> dict[str, Any]:
    """모바일 출력(이 기기 스피커)용 HTTP 스트림 URL."""
    if provider == "tidal":
        url, err = await _tidal_stream_url(stream_id)
        return {
            "ok": bool(url),
            "url": url or "",
            "preview": False,
            "error": err or ("" if url else "tidal stream unavailable"),
        }
    if provider == "spotify":
        tid = _spotify_track_id(stream_id)
        data = await _spotify_api("GET", f"/tracks/{tid}") if tid else None
        preview = str((data or {}).get("preview_url") or "")
        if preview.startswith("http"):
            return {"ok": True, "url": preview, "preview": True}
        if _lab_mode():
            return {"ok": True, "url": LAB_STREAM_URL, "preview": False, "lab": True}
        return {
            "ok": False,
            "url": "",
            "preview": False,
            "error": "Spotify 30초 preview 없음 · 미니PC 스피커 또는 Spotify 앱 Connect 사용",
        }
    return {"ok": False, "url": "", "error": "unknown provider"}


async def play_streaming_track(
    provider: ProviderId,
    stream_id: str,
    meta: dict[str, Any] | None = None,
    *,
    queue: list[dict[str, Any]] | None = None,
    mpd_play: bool = True,
) -> dict[str, Any]:
    meta = meta or {}
    if provider == "spotify":
        res = await play_spotify(stream_id, queue=queue, mpd_play=mpd_play)
    elif provider == "tidal":
        res = await play_tidal(stream_id, queue=queue, mpd_play=mpd_play)
    else:
        return {"ok": False, "error": "unknown provider"}
    res["provider"] = provider
    res["stream_id"] = stream_id
    res["title"] = meta.get("title", "")
    res["artist"] = meta.get("artist", "")
    return res


async def spotify_player_action(action: str) -> bool:
    path_map = {
        "pause": ("PUT", "/me/player/pause"),
        "play": ("PUT", "/me/player/play"),
        "next": ("POST", "/me/player/next"),
        "prev": ("POST", "/me/player/previous"),
    }
    spec = path_map.get(action)
    if not spec:
        return False
    method, path = spec
    if not await _spotify_access_token():
        return _lab_mode()
    data = await _spotify_api(method, path, json={} if method == "PUT" else None)
    return data is not None or _lab_mode()


def store_spotify_web_token(access_token: str, refresh_token: str = "", expires_in: int = 3600) -> None:
    streaming_providers._ensure_dir()
    SPOTIFY_CREDS.write_text(
        json.dumps(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": expires_in,
                "stored_at": streaming_providers._utc_now(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def clear_spotify_web_token() -> None:
    SPOTIFY_CREDS.unlink(missing_ok=True)
