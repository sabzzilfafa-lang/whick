from __future__ import annotations

from typing import Any

import httpx

# siteRadio.js (cc-api) 와 동기화 — 채널 추가 시 양쪽 갱신
RADIO_STATIONS: list[dict[str, Any]] = [
    {"id": "kbs-1radio", "name": "KBS 1라디오", "org": "KBS", "desc": "뉴스·시사", "category": "terrestrial", "kind": "kbs", "param": "21", "emoji": "📻"},
    {"id": "kbs-2radio", "name": "KBS 2라디오", "org": "KBS", "desc": "생활정보", "category": "terrestrial", "kind": "kbs", "param": "22", "emoji": "📻"},
    {"id": "kbs-3radio", "name": "KBS 3라디오", "org": "KBS", "desc": "음악·문화", "category": "terrestrial", "kind": "kbs", "param": "23", "emoji": "🎵"},
    {"id": "kbs-1fm", "name": "KBS 1FM", "org": "KBS", "desc": "클래식", "category": "terrestrial", "kind": "kbs", "param": "24", "emoji": "🎼"},
    {"id": "kbs-coolfm", "name": "KBS Cool FM", "org": "KBS", "desc": "대중음악", "category": "terrestrial", "kind": "kbs", "param": "25", "emoji": "🎵"},
    {"id": "kbs-hanmin", "name": "KBS 한민족방송", "org": "KBS", "desc": "전통·국악", "category": "terrestrial", "kind": "kbs", "param": "26", "emoji": "🎶"},
    {"id": "mbc-sfm", "name": "MBC 표준FM", "org": "MBC", "desc": "표준FM", "category": "terrestrial", "kind": "mbc", "param": "sfm", "emoji": "📻"},
    {"id": "mbc-fm4u", "name": "MBC FM4U", "org": "MBC", "desc": "FM4U", "category": "terrestrial", "kind": "mbc", "param": "mfm", "emoji": "🎤"},
    {"id": "sbs-love", "name": "SBS 러브FM", "org": "SBS", "desc": "러브FM", "category": "terrestrial", "kind": "sbs", "param": "lovepc/lovefm", "emoji": "❤️"},
    {"id": "sbs-power", "name": "SBS 파워FM", "org": "SBS", "desc": "파워FM", "category": "terrestrial", "kind": "sbs", "param": "powerpc/powerfm", "emoji": "⚡"},
    {
        "id": "ebs-fm",
        "name": "EBS FM",
        "org": "EBS",
        "desc": "교육·교양",
        "category": "terrestrial",
        "kind": "url",
        "param": "https://ebsonair.ebs.co.kr/fmradiofamilypc/familypc1m/playlist.m3u8",
        "emoji": "📚",
    },
    {
        "id": "tbs-fm",
        "name": "TBS FM",
        "org": "TBS",
        "desc": "서울 교통방송",
        "category": "internet",
        "kind": "url",
        "param": "https://cdnfm.tbs.seoul.kr/tbs/_definst_/tbs_fm_web_360.smil/playlist.m3u8",
        "emoji": "🚗",
    },
    {
        "id": "tbs-efm",
        "name": "TBS eFM",
        "org": "TBS",
        "desc": "영어 종합",
        "category": "internet",
        "kind": "url",
        "param": "https://cdnefm.tbs.seoul.kr/tbs/_definst_/tbs_efm_web_360.smil/playlist.m3u8",
        "emoji": "🌐",
    },
    # ── Hi-Res 음악전문방송국 (인터넷 FLAC · 무료 스트림) ──
    {
        "id": "hires-radio-calico",
        "name": "Radio Calico",
        "org": "미국",
        "desc": "24bit/48kHz FLAC · 광고없음",
        "category": "hires",
        "kind": "url",
        "param": "https://stream.radio-calico.com/calico",
        "emoji": "🐱",
    },
    {
        "id": "hires-jb-radio-2",
        "name": "JB Radio-2",
        "org": "벨기에",
        "desc": "24bit/96kHz FLAC · 클래식·재즈·팝",
        "category": "hires",
        "kind": "url",
        "param": "https://mediacp.jb-radio.net:8001/flac",
        "emoji": "🎷",
    },
    {
        "id": "hires-intense-radio",
        "name": "Intense Radio",
        "org": "네덜란드",
        "desc": "24bit/44.1kHz FLAC · EDM/Dance · 무료",
        "category": "hires",
        "kind": "url",
        "param": "https://secure.live-streams.nl/flac.flac",
        "emoji": "⚡",
    },
    {
        "id": "hires-radio-paradise",
        "name": "Radio Paradise",
        "org": "미국",
        "desc": "16bit/44.1kHz FLAC · 무손실 무료",
        "category": "hires",
        "kind": "url",
        "param": "https://stream.radioparadise.com/flac",
        "emoji": "🌴",
    },
    {
        "id": "hires-the-cheese",
        "name": "The Cheese",
        "org": "뉴질랜드",
        "desc": "16bit/44.1kHz FLAC · 무손실 스트림",
        "category": "hires",
        "kind": "url",
        "param": "https://station.thecheese.co.nz/listen/the_cheese/flac",
        "emoji": "🧀",
    },
]


def radio_station_by_id(station_id: str) -> dict[str, Any] | None:
    sid = str(station_id or "").strip()
    for station in RADIO_STATIONS:
        if station["id"] == sid:
            return station
    return None


def radio_public_station(station: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": station["id"],
        "name": station["name"],
        "org": station["org"],
        "desc": station["desc"],
        "emoji": station.get("emoji"),
        "category": station.get("category") or "terrestrial",
    }


async def resolve_radio_stream_url(station: dict[str, Any]) -> str:
    kind = str(station.get("kind") or "")
    param = str(station.get("param") or "")
    headers = {"User-Agent": "WhickRadio/1.0"}

    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers) as client:
        if kind in ("url", "ebs"):
            return param
        if kind == "kbs":
            url = f"https://cfpwwwapi.kbs.co.kr/api/v1/landing/live/channel_code/{param}"
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            service = str((data.get("channel_item") or [{}])[0].get("service_url") or "").strip()
            if not service:
                raise RuntimeError("KBS 재생 URL이 없습니다.")
            return service
        if kind == "mbc":
            url = f"https://sminiplay.imbc.com/aacplay.ashx?agent=webapp&channel={param}"
            text = (await client.get(url)).text.strip()
            if not text.startswith("http"):
                raise RuntimeError("MBC 재생 URL이 없습니다.")
            return text
        if kind == "sbs":
            url = f"https://apis.sbs.co.kr/play-api/1.0/livestream/{param}?protocol=hls&ssl=Y"
            text = (await client.get(url)).text.strip()
            if not text.startswith("http"):
                raise RuntimeError("SBS 재생 URL이 없습니다.")
            return text
    raise RuntimeError("알 수 없는 방송 유형입니다.")
