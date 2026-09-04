"""고객 뮤직서버 날씨 컨텍스트 (기상청 초단기실황 → Open-Meteo 폴백, AI DJ용)."""
from __future__ import annotations

import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen

DEFAULT_GEO = {"lat": 37.5665, "lon": 126.978, "city": "서울", "region": "대한민국"}
_CACHE: dict[str, dict[str, Any]] = {}
_TTL_SEC = 20 * 60  # 실황 갱신 주기 고려 (초단기 ~1시간)

# 공인 IP 기반 위치 추정 — GPS 권한 없을 때 서울 하드코딩 대신 사용.
# 도시 단위 근사치라 approximate=True는 유지하되 ipBased=True로 구분.
_IP_GEO_CACHE: dict[str, Any] | None = None
_IP_GEO_AT = 0.0
_IP_GEO_TTL_SEC = 6 * 60 * 60  # 공인 IP는 자주 안 바뀜 — 요청 절약

KST = timezone(timedelta(hours=9))
KMA_BASE = (
    os.getenv("WHICK_KMA_BASE_URL")
    or "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0"
).rstrip("/")


def _kma_service_key() -> str:
    raw = (os.getenv("WHICK_KMA_SERVICE_KEY") or os.getenv("KMA_SERVICE_KEY") or "").strip()
    if not raw:
        return ""
    # 포털이 준 URL-인코딩 키도 허용
    return unquote(raw)


def _kst_hour() -> int:
    # Asia/Seoul = UTC+9 (DST 없음)
    return int((time.time() + 9 * 3600) % 86400 // 3600)


def _period_from_hour(hour: int) -> tuple[str, str]:
    if hour < 6:
        return "Dawn", "🌌"
    if hour < 11:
        return "Morning", "🌅"
    if hour < 14:
        return "Afternoon", "☀️"
    if hour < 18:
        return "Afternoon", "🌤"
    if hour < 22:
        return "Evening", "🌆"
    return "Night", "🌙"


def _wmo_to_weather(code: int, wind_ms: float) -> tuple[str, str]:
    c = int(code or 0)
    wind = float(wind_ms or 0)
    if c in (0, 1):
        return "Sunny", "☀️"
    if c in (2, 3, 45, 48):
        return "Cloudy", "☁️"
    if (51 <= c <= 67) or (80 <= c <= 82) or c == 95 or (96 <= c <= 99):
        return "Rainy", "🌧"
    if (71 <= c <= 77) or (85 <= c <= 86):
        return "Snowy", "❄️"
    if wind >= 10:
        return "Windy", "🍃"
    return "Sunny", "☀️"


def _pty_to_weather(pty: int, wind_ms: float) -> tuple[str, str]:
    """기상청 초단기실황 PTY 코드 → UI 카테고리."""
    p = int(pty or 0)
    wind = float(wind_ms or 0)
    if p in (1, 5):  # 비, 빗방울
        return "Rainy", "🌧"
    if p in (2, 6):  # 비/눈, 빗방울눈날림
        return "Rainy", "🌧"
    if p in (3, 7):  # 눈, 눈날림
        return "Snowy", "❄️"
    if p == 4:  # 소나기
        return "Rainy", "🌧"
    if wind >= 10:
        return "Windy", "🍃"
    return "Sunny", "☀️"


def _fetch_json(url: str, timeout: float = 8.0, extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "whick-music-server/1.0"}
    if extra_headers:
        headers.update(extra_headers)
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        import json

        return json.loads(resp.read().decode("utf-8"))


def _parse_lat_lon(lat: Any, lon: Any) -> dict[str, float] | None:
    try:
        la = float(lat)
        lo = float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90 <= la <= 90 and -180 <= lo <= 180):
        return None
    return {"lat": la, "lon": lo}


def _pick_admin_city(address: dict[str, Any] | None) -> tuple[str, str]:
    a = address or {}
    city = str(
        a.get("city")
        or a.get("town")
        or a.get("municipality")
        or a.get("county")
        or a.get("city_district")
        or ""
    ).strip()
    region = str(a.get("province") or a.get("state") or a.get("region") or "").strip()
    return city.replace(" ", ""), region.replace(" ", "") if region else region


def _reverse_geocode_ko(lat: float, lon: float) -> dict[str, str] | None:
    """GPS/IP 좌표 → 시·광역시 라벨 (Nominatim).
    언어는 WHICK_GEO_LANG(env)으로 선택 — 기본 ko, 영문 UI 서버는 en 가능."""
    lang = (os.getenv("WHICK_GEO_LANG") or "ko").strip().lower() or "ko"
    try:
        q = urlencode(
            {
                "lat": f"{lat}",
                "lon": f"{lon}",
                "format": "json",
                "accept-language": lang,
                "zoom": "10",
            }
        )
        j = _fetch_json(
            f"https://nominatim.openstreetmap.org/reverse?{q}",
            timeout=6.0,
            extra_headers={"User-Agent": "WhickMusicWeather/1.0 (whick.org)"},
        )
        city, region = _pick_admin_city(j.get("address") if isinstance(j, dict) else None)
        if city:
            return {"city": city, "region": region}
    except Exception:
        return None
    return None


def _needs_city_label(city: str) -> bool:
    s = str(city or "").strip()
    if not s or s in ("현재 위치", "현재 지역"):
        return True
    # 영문 GeoIP 도시명 → 한글 시·광역시로 교체
    if not any("\uac00" <= ch <= "\ud7a3" for ch in s):
        return True
    return False


def _enrich_geo_label(geo: dict[str, Any]) -> dict[str, Any]:
    if _needs_city_label(str(geo.get("city") or "")):
        rev = _reverse_geocode_ko(float(geo["lat"]), float(geo["lon"]))
        if rev and rev.get("city"):
            geo = {**geo, "city": rev["city"], "region": rev.get("region") or geo.get("region") or ""}
    return geo


def _geo_from_env() -> dict[str, Any] | None:
    """설치·고객 고정 위치 (미니PC가 터널로 서울 IP가 되는 경우 대비)."""
    coords = _parse_lat_lon(os.getenv("WHICK_GEO_LAT"), os.getenv("WHICK_GEO_LON"))
    if not coords:
        return None
    city = (os.getenv("WHICK_GEO_CITY") or "").strip() or "설정 위치"
    region = (os.getenv("WHICK_GEO_REGION") or "").strip()
    return {
        "lat": coords["lat"],
        "lon": coords["lon"],
        "city": city,
        "region": region,
    }


def _geo_from_ip() -> dict[str, Any] | None:
    """공인 IP → 대략적 위치(도시 단위). 실패하면 None(호출측이 서울 기본값으로 폴백)."""
    global _IP_GEO_CACHE, _IP_GEO_AT
    now = time.time()
    if _IP_GEO_CACHE and now - _IP_GEO_AT < _IP_GEO_TTL_SEC:
        return _IP_GEO_CACHE
    try:
        j = _fetch_json(
            "http://ip-api.com/json/?fields=status,lat,lon,city,regionName,country",
            timeout=5.0,
        )
        if j.get("status") != "success":
            return None
        la, lo = j.get("lat"), j.get("lon")
        if la is None or lo is None:
            return None
        result = {
            "lat": float(la),
            "lon": float(lo),
            "city": j.get("city") or "",
            "region": j.get("regionName") or j.get("country") or "",
        }
    except Exception:
        return None
    _IP_GEO_CACHE = result
    _IP_GEO_AT = now
    return result


def latlon_to_kma_grid(lat: float, lon: float) -> tuple[int, int]:
    """위경도 → 기상청 격자 (nx, ny). 공식 변환 (5km)."""
    re = 6371.00877 / 5.0
    slat1 = 30.0 * math.pi / 180.0
    slat2 = 60.0 * math.pi / 180.0
    olon = 126.0 * math.pi / 180.0
    olat = 38.0 * math.pi / 180.0
    xo, yo = 43, 136
    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = math.pow(sf, sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re * sf / math.pow(ro, sn)
    ra = math.tan(math.pi * 0.25 + lat * math.pi / 180.0 * 0.5)
    ra = re * sf / math.pow(ra, sn)
    theta = lon * math.pi / 180.0 - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn
    x = ra * math.sin(theta) + xo + 1.5
    y = ro - ra * math.cos(theta) + yo + 1.5
    return int(x), int(y)


def _kma_base_datetime() -> tuple[str, str]:
    """초단기실황 base_date / base_time (매시 40분 이후 당시 시각 반영)."""
    now = datetime.now(KST)
    base = now
    if base.minute < 40:
        base = base - timedelta(hours=1)
    return base.strftime("%Y%m%d"), base.strftime("%H00")


def _weather_from_kma(lat: float, lon: float) -> dict[str, Any]:
    """공공데이터 기상청 getUltraSrtNcst (초단기실황)."""
    key = _kma_service_key()
    if not key:
        raise RuntimeError("WHICK_KMA_SERVICE_KEY not set")

    nx, ny = latlon_to_kma_grid(lat, lon)
    base_date, base_time = _kma_base_datetime()
    q = urlencode(
        {
            "serviceKey": key,
            "pageNo": "1",
            "numOfRows": "100",
            "dataType": "JSON",
            "base_date": base_date,
            "base_time": base_time,
            "nx": str(nx),
            "ny": str(ny),
        }
    )
    url = f"{KMA_BASE}/getUltraSrtNcst?{q}"
    j = _fetch_json(url, timeout=10.0)
    header = (j.get("response") or {}).get("header") or {}
    if str(header.get("resultCode") or "") not in ("00", "0", ""):
        raise RuntimeError(f"kma {header.get('resultCode')}: {header.get('resultMsg')}")

    items = ((j.get("response") or {}).get("body") or {}).get("items") or {}
    raw = items.get("item") if isinstance(items, dict) else items
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise RuntimeError("kma empty items")

    cats: dict[str, str] = {}
    for it in raw:
        if not isinstance(it, dict):
            continue
        cat = str(it.get("category") or "").strip()
        val = it.get("obsrValue")
        if cat and val is not None:
            cats[cat] = str(val).strip()

    if "T1H" not in cats:
        raise RuntimeError("kma missing T1H")

    # T1H 소수 1자리 (예: 31.3) — 정수 반올림으로 체감 오차 내지 않음
    temp = round(float(cats["T1H"]), 1)
    pty = int(float(cats.get("PTY") or 0))
    wind = float(cats.get("WSD") or 0)
    weather, w_emoji = _pty_to_weather(pty, wind)
    return {
        "temp": temp,
        "weatherCode": pty,  # KMA PTY (source=kma 일 때)
        "windMs": wind,
        "pty": pty,
        "reh": cats.get("REH"),
        "nx": nx,
        "ny": ny,
        "baseDate": base_date,
        "baseTime": base_time,
        "provider": "kma",
        "weather": weather,
        "wEmoji": w_emoji,
    }


def _weather_from_lat_lon_open_meteo(lat: float, lon: float) -> dict[str, Any]:
    q = urlencode(
        {
            "latitude": f"{lat}",
            "longitude": f"{lon}",
            "current": "temperature_2m,weather_code,wind_speed_10m",
            "timezone": "Asia/Seoul",
            "forecast_days": "1",
        }
    )
    j = _fetch_json(f"https://api.open-meteo.com/v1/forecast?{q}")
    cur = j.get("current") or {}
    if not cur:
        raise RuntimeError("no current weather")
    return {
        "temp": round(float(cur.get("temperature_2m")), 1),
        "weatherCode": int(cur.get("weather_code") or 0),
        "windMs": float(cur.get("wind_speed_10m") or 0),
        "provider": "open-meteo",
    }


def _is_korea_coord(lat: float, lon: float) -> bool:
    """대한민국 영토 대략 범위 (위 33~39, 경 124~132)."""
    return 33.0 <= float(lat) <= 39.0 and 124.0 <= float(lon) <= 132.0


def _weather_from_lat_lon(lat: float, lon: float) -> dict[str, Any]:
    """한국 좌표면 기상청 우선 → Open-Meteo 폴백.
    외국 좌표면 KMA가 커버하지 않으므로 Open-Meteo 직행 (파파 지시 2026-09-03)."""
    prefer = (os.getenv("WHICK_WEATHER_PROVIDER") or "kma").strip().lower()
    errors: list[str] = []

    in_korea = _is_korea_coord(lat, lon)
    if prefer != "open-meteo" and in_korea and _kma_service_key():
        try:
            return _weather_from_kma(lat, lon)
        except Exception as e:
            errors.append(f"kma:{e}")

    try:
        om = _weather_from_lat_lon_open_meteo(lat, lon)
        weather, w_emoji = _wmo_to_weather(om["weatherCode"], om["windMs"])
        om["weather"] = weather
        om["wEmoji"] = w_emoji
        return om
    except Exception as e:
        errors.append(f"open-meteo:{e}")
        raise RuntimeError("; ".join(errors) or "weather fetch failed") from e


def get_weather_context(*, lat: Any = None, lon: Any = None) -> dict[str, Any]:
    """GPS 좌표 우선 → env 고정 → 공인 IP 추정 → 실패 시 서울 기본 좌표.
    실황: 기상청 초단기실황(고객 좌표 격자) → Open-Meteo.
    """
    manual = _parse_lat_lon(lat, lon)
    env_geo = None if manual else _geo_from_env()
    ip_geo = None if (manual or env_geo) else _geo_from_ip()

    if manual:
        cache_key = f"geo:{manual['lat']:.2f},{manual['lon']:.2f}"
    elif env_geo:
        cache_key = f"envgeo:{env_geo['lat']:.2f},{env_geo['lon']:.2f}"
    elif ip_geo:
        cache_key = f"ipgeo:{ip_geo['lat']:.2f},{ip_geo['lon']:.2f}"
    else:
        cache_key = "default"

    hit = _CACHE.get(cache_key)
    now = time.time()
    if hit and now - float(hit.get("at") or 0) < _TTL_SEC:
        return hit["data"]

    ip_based = False
    if manual:
        geo = {
            **DEFAULT_GEO,
            "lat": manual["lat"],
            "lon": manual["lon"],
            "city": "현재 위치",
            "region": "",
        }
        geo = _enrich_geo_label(geo)
        approximate = False
    elif env_geo:
        geo = {
            **DEFAULT_GEO,
            "lat": env_geo["lat"],
            "lon": env_geo["lon"],
            "city": env_geo.get("city") or DEFAULT_GEO["city"],
            "region": env_geo.get("region") or "",
        }
        geo = _enrich_geo_label(geo)
        approximate = True
    elif ip_geo:
        geo = {
            **DEFAULT_GEO,
            "lat": ip_geo["lat"],
            "lon": ip_geo["lon"],
            "city": ip_geo.get("city") or DEFAULT_GEO["city"],
            "region": ip_geo.get("region") or "",
        }
        geo = _enrich_geo_label(geo)
        approximate = True
        ip_based = True
    else:
        geo = dict(DEFAULT_GEO)
        approximate = True

    hour = _kst_hour()
    period, p_emoji = _period_from_hour(hour)
    wx = None
    try:
        wx = _weather_from_lat_lon(geo["lat"], geo["lon"])
    except Exception:
        if hit and hit.get("data"):
            stale = dict(hit["data"])
            stale.update(
                {
                    "source": "cache-stale",
                    "stale": True,
                    "hour": hour,
                    "period": period,
                    "pEmoji": p_emoji,
                }
            )
            return stale

    if wx:
        weather = str(wx.get("weather") or "맑음")
        w_emoji = str(wx.get("wEmoji") or "☀️")
        source = str(wx.get("provider") or "open-meteo")
    else:
        weather, w_emoji = "정보없음", "🌐"
        source = "location-fallback"

    data = {
        "source": source,
        "ipBased": ip_based,
        "approximate": approximate,
        "city": geo["city"],
        "region": geo.get("region") or "",
        "locationLabel": " · ".join([x for x in (geo["city"], geo.get("region")) if x])
        or geo["city"],
        "hour": hour,
        "period": period,
        "pEmoji": p_emoji,
        "weather": weather,
        "wEmoji": w_emoji,
        "temp": wx["temp"] if wx else None,
        "windMs": wx["windMs"] if wx else None,
        "weatherCode": wx["weatherCode"] if wx else None,
        "lat": geo["lat"],
        "lon": geo["lon"],
    }
    if wx and wx.get("provider") == "kma":
        data["kma"] = {
            "nx": wx.get("nx"),
            "ny": wx.get("ny"),
            "baseDate": wx.get("baseDate"),
            "baseTime": wx.get("baseTime"),
            "pty": wx.get("pty"),
            "reh": wx.get("reh"),
        }
    _CACHE[cache_key] = {"at": now, "data": data}
    return data
