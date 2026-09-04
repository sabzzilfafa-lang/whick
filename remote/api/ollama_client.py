"""Ollama gemma4:e2b/e4b — 검색 Intent·분류로봇 키워드 생성 (검색 본체는 PostgreSQL)."""
from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e2b")
HTTP_TIMEOUT = httpx.Timeout(connect=1.5, read=8.0, write=4.0, pool=2.0)
# 분류로봇(스캔 중 백그라운드, 트랙당 1회)은 사용자 응답 지연과 무관하므로
# CPU-only 기기의 느린 생성 시간(10초+)을 버틸 여유 있는 타임아웃을 쓴다.
CLASSIFY_HTTP_TIMEOUT = httpx.Timeout(connect=1.5, read=45.0, write=4.0, pool=2.0)
# AI 추천: 프롬프트 축소 + 생성 상한. 너무 길면 UX가 “멈춤”처럼 보임.
RECOMMEND_HTTP_TIMEOUT = httpx.Timeout(
    connect=1.5,
    read=float(os.getenv("OLLAMA_RECOMMEND_READ_S", "18")),
    write=4.0,
    pool=2.0,
)
RECOMMEND_CATALOG_LIMIT = max(12, min(int(os.getenv("OLLAMA_RECOMMEND_CATALOG", "28")), 60))
RECOMMEND_NUM_PREDICT = max(64, min(int(os.getenv("OLLAMA_RECOMMEND_NUM_PREDICT", "220")), 512))
RECOMMEND_NUM_CTX = max(2048, min(int(os.getenv("OLLAMA_RECOMMEND_NUM_CTX", "4096")), 16384))

_STATUS_CACHE: dict[str, Any] | None = None
_STATUS_CACHE_AT = 0.0
_STATUS_CACHE_TTL_SEC = 20.0


def ollama_num_gpu() -> int | None:
    """None(auto)이면 Ollama 기본 GPU 감지를 사용한다."""
    raw = os.getenv("OLLAMA_NUM_GPU", "auto").strip().lower()
    if raw in {"", "auto", "default"}:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def ollama_generate_options() -> dict[str, int]:
    num_gpu = ollama_num_gpu()
    return {} if num_gpu is None else {"num_gpu": num_gpu}


def ollama_num_gpu_label() -> int | str:
    num_gpu = ollama_num_gpu()
    return "auto" if num_gpu is None else num_gpu


def ollama_urls() -> list[str]:
    urls: list[str] = []
    primary = os.getenv("OLLAMA_URL", "").strip()
    if primary:
        urls.append(primary.rstrip("/"))
    for fallback in (
        "http://host.docker.internal:11434",
        "http://172.17.0.1:11434",
        "http://127.0.0.1:11434",
    ):
        if fallback not in urls:
            urls.append(fallback)
    return urls


async def ollama_status(*, force: bool = False) -> dict[str, Any]:
    """가능하면 /api/tags 재조회를 줄여 추천·검색 응답을 늦추지 않는다."""
    global _STATUS_CACHE, _STATUS_CACHE_AT
    now = time.time()
    if (
        not force
        and _STATUS_CACHE
        and now - _STATUS_CACHE_AT < _STATUS_CACHE_TTL_SEC
        and _STATUS_CACHE.get("ok")
    ):
        return dict(_STATUS_CACHE)

    for url in ollama_urls():
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.get(f"{url}/api/tags")
                if resp.status_code != 200:
                    continue
                models = [m.get("name") for m in (resp.json().get("models") or [])]
                ok = OLLAMA_MODEL in models or any(
                    str(m).split(":")[0] == OLLAMA_MODEL.split(":")[0] for m in models
                )
                status = {
                    "ok": ok,
                    "url": url,
                    "model": OLLAMA_MODEL,
                    "num_gpu": ollama_num_gpu_label(),
                    "models": models[:8],
                }
                _STATUS_CACHE = dict(status)
                _STATUS_CACHE_AT = now
                return status
        except Exception:
            continue
    status = {"ok": False, "url": None, "model": OLLAMA_MODEL, "num_gpu": ollama_num_gpu_label(), "models": []}
    _STATUS_CACHE = dict(status)
    _STATUS_CACHE_AT = now
    return status


async def extract_search_keywords(
    query: str,
    catalog_names: list[str] | None = None,
    catalog_titles: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """검색 Intent 정규화 — 오타 교정·영문 통용명·복합어 분해.

    검색 본체는 PostgreSQL ILIKE. 이 함수는 AI가 사용자 입력을
    라이브러리와 맞물리는 keywords로 확장하는 역할만 한다.
    catalog_names(작곡가·아티스트)·catalog_titles(곡제목)를  squ지 않으면
    작은 모델이 입력을 되풀이하거나 엉뚱한 작품명으로 환각하기 쉽다.
    """
    fallback: dict[str, Any] = {"keywords": [query], "genre": "", "mood": "", "era": ""}
    status = await ollama_status()
    url = status.get("url")
    if not url or not status.get("ok"):
        return fallback, status

    names = [str(n).strip() for n in (catalog_names or []) if str(n).strip()]
    # 프롬프트 길이 제한 — 중복·과장 방지
    seen: set[str] = set()
    uniq_names: list[str] = []
    for n in names:
        key = n.casefold()
        if key in seen:
            continue
        seen.add(key)
        uniq_names.append(n)
        if len(uniq_names) >= 48:
            break
    catalog_line = ""
    if uniq_names:
        catalog_line = "알려진 작곡가/아티스트(이 기기 라이브러리): " + ", ".join(uniq_names) + "\n"

    titles = [str(t).strip() for t in (catalog_titles or []) if str(t).strip()]
    seen_t: set[str] = set()
    uniq_titles: list[str] = []
    for t in titles:
        key = t.casefold()
        if key in seen_t:
            continue
        seen_t.add(key)
        uniq_titles.append(t[:120])
        if len(uniq_titles) >= 60:
            break
    title_line = ""
    if uniq_titles:
        title_line = "라이브러리 곡 제목(이 목록에서만 작품 매칭): " + " | ".join(uniq_titles) + "\n"

    prompt = (
        f"음악 라이브러리 검색어 정규화. 사용자 입력: {query}\n"
        f"{catalog_line}"
        f"{title_line}"
        "규칙:\n"
        "(1) 오타·변형 한글 표기를 올바른 이름·영어 통용명으로 교정 "
        "(예: 베토밴→Beethoven, 모짜르트→Mozart)\n"
        "(2) 한글 작품명·별칭은 위 라이브러리 곡 제목과 매칭 "
        "(예: 핑갈의 동굴→Fingal's Cave 또는 Hebrides — 제목 목록에 있을 때만)\n"
        "(3) 복합 문장은 의미 단위로 분해 (예: 느린 베토벤→Beethoven, 느림)\n"
        "(4) 작곡가·작품이면 영어 이름 반드시 포함\n"
        "(5) keywords는 2~6개. 원본 검색어만 되풀이하지 말 것\n"
        "(6) mood/genre/era는 해당될 때만 채움\n"
        "(7) 사용자가 말하지 않은 작곡가/작품을 catalog·제목 목록에 없는데 "
        "지어내지 말 것 (Pygmalion 등 환각 금지). "
        "분위기만 있으면 검색 가능한 분위기·장르 단어로만 옮기고, "
        "옮길 수 없으면 keywords는 빈 배열\n"
        '{"keywords":["..."],"genre":"","mood":"","era":""}'
    )
    # 검색 UX: CPU-only e2b/e4b도 한 번 생성이 끝날 여유
    search_timeout = httpx.Timeout(connect=1.5, read=20.0, write=4.0, pool=2.0)
    try:
        async with httpx.AsyncClient(timeout=search_timeout) as client:
            resp = await client.post(
                f"{url}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": ollama_generate_options(),
                },
            )
            if resp.status_code == 200:
                parsed = json.loads(resp.json().get("response") or "{}")
                if isinstance(parsed, dict):
                    kws = parsed.get("keywords")
                    if isinstance(kws, list) and kws:
                        # 공백 복합어는 토큰으로도 펼침 (느린 베토벤 등)
                        _GENERIC_TITLE_TOKENS = {
                            "overture", "symphony", "concerto", "sonata", "prelude",
                            "fugue", "quartet", "quintet", "suite", "op", "op.",
                            "cave", "movement", "allegro", "andante", "adagio",
                            "no", "no.", "in", "the", "a", "of", "and",
                            "서곡", "교향곡", "협주곡", "소나타",
                        }
                        expanded: list[str] = []
                        for item in kws:
                            s = " ".join(str(item or "").split()).strip()
                            if not s:
                                continue
                            expanded.append(s)
                            if " " in s:
                                for part in s.split(" "):
                                    clean = part.strip('",.')
                                    if len(clean) < 3:
                                        continue
                                    if clean.casefold() in _GENERIC_TITLE_TOKENS:
                                        continue
                                    expanded.append(clean)
                        # 제목 목록에 없는 환각 작품명 제거 (입력에 직접 나온 것은 유지)
                        q_cf = (query or "").casefold()
                        title_blob = " ".join(uniq_titles).casefold()
                        name_blob = " ".join(uniq_names).casefold()
                        grounded: list[str] = []
                        for s in expanded:
                            sc = s.casefold()
                            if sc in q_cf or s in (query or ""):
                                grounded.append(s)
                            elif uniq_titles and (sc in title_blob or any(
                                sc in t.casefold() or t.casefold() in sc for t in uniq_titles if len(sc) >= 3
                            )):
                                grounded.append(s)
                            elif uniq_names and (sc in name_blob or any(
                                sc in n.casefold() or n.casefold() in sc for n in uniq_names if len(sc) >= 3
                            )):
                                grounded.append(s)
                            elif not uniq_titles:
                                grounded.append(s)
                        parsed["keywords"] = grounded or expanded
                        return parsed, {**status, "used_url": url}
                    if isinstance(kws, list) and not kws:
                        return parsed, {**status, "used_url": url}
    except Exception as exc:
        print(f"[AI] generate {url}: {exc}")
    return fallback, status


async def match_library_title(
    query: str,
    catalog_titles: list[str] | None,
) -> tuple[str | None, dict[str, Any]]:
    """한글 작품명 등 → 라이브러리 제목 중 가장 가까운 것 1개 (없으면 None)."""
    status = await ollama_status()
    url = status.get("url")
    titles = [str(t).strip() for t in (catalog_titles or []) if str(t).strip()]
    if not url or not status.get("ok") or not titles:
        return None, status
    # 번호 목록 — 모델이 목록 밖으로 못 나가게
    lines = [f"{i+1}. {t[:120]}" for i, t in enumerate(titles[:50])]
    prompt = (
        f"사용자 검색어: {query}\n"
        "아래는 이 기기 라이브러리 곡 제목입니다. "
        "검색어(한글 별칭·오타 포함)와 같은 작품을 고르세요.\n"
        + "\n".join(lines)
        + "\n규칙: 목록에 있는 번호만. 확실하지 않으면 index=null — 아무 곡이나 짐작하지 말 것. 검색어가 그 작품을 분명히 가리킬 때만 매칭. "
        + 'JSON만: {"index":1,"title":"..."} 또는 {"index":null,"title":""}\n'
        "예: 핑갈의 동굴 → Fingal's Cave / Hebrides 가 있는 번호"
    )
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=1.5, read=20.0, write=4.0, pool=2.0)
        ) as client:
            resp = await client.post(
                f"{url}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": ollama_generate_options(),
                },
            )
            if resp.status_code == 200:
                parsed = json.loads(resp.json().get("response") or "{}")
                if not isinstance(parsed, dict):
                    return None, status
                idx = parsed.get("index")
                title = str(parsed.get("title") or "").strip()
                if idx is None or idx == "" or idx == 0 or str(idx).lower() == "null":
                    return None, {**status, "used_url": url}
                try:
                    i = int(idx) - 1
                except (TypeError, ValueError):
                    i = -1
                if 0 <= i < len(titles):
                    return titles[i], {**status, "used_url": url}
                # title 문자열이 목록에 있으면 허용
                for t in titles:
                    if title and (title.casefold() in t.casefold() or t.casefold() in title.casefold()):
                        return t, {**status, "used_url": url}
    except Exception as exc:
        print(f"[AI] match_title {url}: {exc}")
    return None, status


def _has_hangul(text: str) -> bool:
    return any("\uac00" <= ch <= "\ud7a3" for ch in (text or ""))

# 분류로봇: 곡당 검색 키워드 상한 (무리 없는 선에서 최대한 유용하게)
TRACK_SEARCH_KEYWORDS_MAX = 5


def _normalize_track_keywords(raw: list[Any]) -> list[str]:
    """중복·공백 제거 후 최대 TRACK_SEARCH_KEYWORDS_MAX개."""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        kw = " ".join(str(item or "").split()).strip()
        if not kw:
            continue
        key = kw.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(kw)
        if len(out) >= TRACK_SEARCH_KEYWORDS_MAX:
            break
    return out


async def generate_track_search_keywords(meta: dict[str, Any]) -> str | None:
    """분류로봇: 트랙 1개당 1회, 검색 보조 키워드를 최대 5개 생성.

    실패·AI 미가동 시 None — 호출측이 재시도(다음 스캔)할 수 있도록 컬럼을 비워둔다.
    """
    status = await ollama_status()
    url = status.get("url")
    if not url or not status.get("ok"):
        return None

    fields = " · ".join(
        f"{label}={value}"
        for label, value in (
            ("제목", meta.get("title")),
            ("아티스트", meta.get("artist")),
            ("앨범", meta.get("album")),
            ("장르", meta.get("genre")),
            ("작곡가", meta.get("composer")),
        )
        if value
    )
    if not fields:
        return None

    prompt = (
        f"음원 메타데이터: {fields}\n"
        "검색용 키워드 JSON만 출력. keywords는 정확히 5개 이내.\n"
        "우선순위: (1) 한글 별칭·번역 (2) 영어 원제/핵심어 (3) 작곡가·아티스트 짧은 이름 "
        "(4) 장르·무드 1개. 제목 전체를 길게 반복하지 말 것.\n"
        '예: Marriage of Figaro → {"keywords":["결혼","피가로","모차르트","opera","classical"]}\n'
        '{"keywords":["..."]}'
    )
    try:
        async with httpx.AsyncClient(timeout=CLASSIFY_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{url}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": ollama_generate_options(),
                },
            )
            if resp.status_code == 200:
                parsed = json.loads(resp.json().get("response") or "{}")
                keywords = _normalize_track_keywords(parsed.get("keywords") or [])
                if keywords:
                    return " ".join(keywords)
    except Exception as exc:
        print(f"[AI] track keywords {url}: {exc!r}")
    return None


async def extract_recommend_track_ids(
    tracks: list[dict[str, Any]],
    limit: int = 8,
    context: str = "",
    lang: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """로컬 catalog에서 AI DJ 추천 track_id 목록."""
    fallback: dict[str, Any] = {"track_ids": [], "reasons": {}, "explain": ""}
    if not tracks:
        return fallback, {"ok": False, "url": None, "model": OLLAMA_MODEL}

    status = await ollama_status()
    url = status.get("url")
    if not url or not status.get("ok"):
        return fallback, status

    # 짧은 메타만 — 100곡 풀 카탈로그는 e2b에서도 생성 지연·타임아웃 원인
    catalog = [
        {
            "id": str(t.get("track_id") or t.get("id") or ""),
            "t": str(t.get("title") or "")[:80],
            "a": str(t.get("artist") or "")[:48],
            "g": str(t.get("genre") or "")[:28],
            "u": int(t.get("play_count") or 0) == 0,
        }
        for t in tracks[:RECOMMEND_CATALOG_LIMIT]
        if t.get("track_id") or t.get("id")
    ]
    if not catalog:
        return fallback, status

    lim = max(1, min(int(limit or 8), 20))
    ctx_line = f"취향/날씨: {str(context)[:240]}\n" if context else ""

    # ko가 아닌 모든 언어는 영어 프롬프트 (파파 지시 2026-08-17)
    is_en = lang is not None and lang != "ko"
    if is_en:
        prompt = (
            "Personal AI DJ. Use only ids from catalog.\n"
            f"{'Context (taste/weather): ' + str(context)[:240] + chr(10) if context else ''}"
            "Rules: prefer u=true (unplayed), match taste (a·g).\n"
            f"catalog:{json.dumps(catalog, ensure_ascii=False)}\n"
            f'JSON only: {{"track_ids":["id",...],"reasons":{{"id":"one line"}},"explain":"one line"}}\n'
            f"track_ids max {lim}."
        )
    else:
        prompt = (
            "개인 AI DJ. catalog 의 id 만 사용.\n"
            f"{ctx_line}"
            "규칙: u=true(미재생) 우선, 취향(a·g)에 맞는 곡.\n"
            f"catalog:{json.dumps(catalog, ensure_ascii=False)}\n"
            f'JSON만: {{"track_ids":["id",...],"reasons":{{"id":"한 줄"}},"explain":"한 줄"}}\n'
            f"track_ids 최대 {lim}."
        )
    opts = {
        **ollama_generate_options(),
        "temperature": 0.2,
        "num_predict": RECOMMEND_NUM_PREDICT,
        "num_ctx": RECOMMEND_NUM_CTX,
    }
    try:
        async with httpx.AsyncClient(timeout=RECOMMEND_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{url}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": opts,
                },
            )
            if resp.status_code == 200:
                parsed = json.loads(resp.json().get("response") or "{}")
                if isinstance(parsed, dict):
                    allowed = {c["id"] for c in catalog}
                    ids = [
                        str(i)
                        for i in (parsed.get("track_ids") or [])
                        if str(i) in allowed
                    ][:lim]
                    reasons = parsed.get("reasons") if isinstance(parsed.get("reasons"), dict) else {}
                    return {
                        "track_ids": ids,
                        "reasons": {str(k): str(v)[:120] for k, v in reasons.items()},
                        "explain": str(parsed.get("explain") or "")[:300],
                    }, {**status, "used_url": url}
    except Exception as exc:
        print(f"[AI] recommend {url}: {exc}")
    return fallback, status


# ── AI 어시스턴트 (채팅 + 라이브러리 도구) ─────────────────────────
CHAT_HTTP_TIMEOUT = httpx.Timeout(connect=1.5, read=45.0, write=4.0, pool=2.0)
WHICK_AI_NAME = "Whick AI"
WHICK_AI_ROLE = "고객 뮤직서버에 있는 개인 AI 어시스턴트"

# 음악 요청으로 볼 표현 — 되묻지 말고 바로 추천/검색
_MUSIC_REQUEST_HINTS = (
    "골라", "고르", "추천", "틀어", "재생", "들려", "듣고", "찾아", "검색",
    "playlist", "play", "recommend", "곡", "음악", "노래",
)


def _looks_like_music_request(message: str) -> bool:
    q = (message or "").strip()
    if not q:
        return False
    return any(h in q for h in _MUSIC_REQUEST_HINTS)


def _polite_music_reply(n: int) -> str:
    if n <= 0:
        return "라이브러리에서 맞는 곡을 찾지 못했습니다."
    if n == 1:
        return "요청하신 곡을 골라 두었습니다."
    return f"요청하신 곡 {n}곡을 골라 두었습니다."


def _unclear_music_reply() -> str:
    """분위기·속어를 DB 검색어로 못 옮길 때 — 엉뚱한 곡 대신 재질문."""
    return (
        "죄송합니다. 말씀하신 분위기를 제가 찾아볼 수 있는 말로 "
        "정확히 이해하지 못했습니다. "
        "작곡가·곡 제목·장르(클래식, 재즈 등)처럼 "
        "라이브러리에서 검색 가능한 단어로 다시 말씀해 주세요."
    )


def match_catalog_in_message(
    message: str, catalog_names: list[str] | None
) -> str | None:
    """메시지에 라이브러리 작곡가/아티스트명이 있으면 가장 긴 매칭."""
    q = (message or "").strip()
    if not q or not catalog_names:
        return None
    ql = q.casefold()
    hits: list[str] = []
    for raw in catalog_names:
        name = str(raw or "").strip()
        if len(name) < 2:
            continue
        if name.casefold() in ql or name in q:
            hits.append(name)
            continue
        for part in name.replace(",", " ").split():
            if len(part) >= 4 and part.casefold() in ql:
                hits.append(name)
                break
    if not hits:
        return None
    hits.sort(key=len, reverse=True)
    return hits[0]


def _is_bare_recommend_request(message: str) -> bool:
    """구체적 단서 없이 '추천만' 요청한 경우."""
    q = "".join((message or "").split()).casefold()
    if not q:
        return False
    bare = {
        "추천",
        "추천해",
        "추천해줘",
        "추천해주세요",
        "노래추천",
        "음악추천",
        "추천곡",
        "아무거나",
        "아무노래",
        "아무노래나",
        "랜덤",
        "recommend",
    }
    return q in bare or (len(q) <= 10 and any(b in q for b in ("아무거나", "랜덤")))


def _fallback_assistant(message: str, weather_summary: str = "") -> dict[str, Any]:
    """Ollama 실패 시 규칙 기반 최소 응답."""
    q = (message or "").strip()
    ql = q.casefold()
    if any(k in q for k in ("이름", "누구", "who are you", "who r u")) or "너는" in q:
        return {
            "intent": "chat",
            "reply": (
                f"안녕하세요. 저는 {WHICK_AI_NAME}입니다. "
                f"{WHICK_AI_ROLE}입니다. 음악 찾기·추천·날씨·일상 대화를 도와드리겠습니다."
            ),
            "search_query": "",
            "recommend": False,
            "play": False,
        }
    if "날씨" in q or "weather" in ql:
        wx = weather_summary or "지금은 날씨 정보를 가져오지 못했습니다."
        return {
            "intent": "chat",
            "reply": wx if wx.endswith(("습니다.", "니다.", "세요.")) else wx + "입니다.",
            "search_query": "",
            "recommend": False,
            "play": False,
        }
    if _looks_like_music_request(q):
        play = any(k in q for k in ("틀어", "재생", "play"))
        if _is_bare_recommend_request(q):
            return {
                "intent": "recommend",
                "reply": "요청하신 곡을 골라 두었습니다.",
                "search_query": "",
                "recommend": True,
                "play": play,
            }
        return {
            "intent": "play" if play else "search",
            "reply": "라이브러리에서 찾아 보겠습니다.",
            "search_query": q,
            "recommend": False,
            "play": play,
        }
    return {
        "intent": "search",
        "reply": "라이브러리에서 찾아 보겠습니다.",
        "search_query": q,
        "recommend": False,
        "play": False,
    }


async def ai_assistant_turn(
    message: str,
    *,
    history: list[dict[str, Any]] | None = None,
    weather_summary: str = "",
    catalog_names: list[str] | None = None,
    library_count: int = 0,
    user_name: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """일반 채팅 + 필요 시 라이브러리 검색/추천 도구를 고르는 한 턴.

    반환 parsed:
      intent: chat|search|recommend|play
      reply: 사용자에게 보여줄 한국어 답변
      search_query: DB 검색에 쓸 짧은 쿼리(작곡가·작품·분위기)
      recommend: True면 카탈로그 추천 도구 사용
      play: True면 첫 곡 자동재생 권장
    """
    fallback = _fallback_assistant(message, weather_summary)
    status = await ollama_status()
    url = status.get("url")
    if not url or not status.get("ok"):
        return fallback, status

    names = [str(n).strip() for n in (catalog_names or []) if str(n).strip()]
    seen: set[str] = set()
    uniq: list[str] = []
    for n in names:
        k = n.casefold()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(n)
        if len(uniq) >= 40:
            break
    catalog_line = ", ".join(uniq) if uniq else "(비어 있음)"

    hist_lines: list[str] = []
    for turn in (history or [])[-6:]:
        role = str(turn.get("role") or "")
        content = str(turn.get("content") or "").strip()
        if not content:
            continue
        who = "사용자" if role == "user" else "AI"
        hist_lines.append(f"{who}: {content[:240]}")
    hist_block = "\n".join(hist_lines) if hist_lines else "(없음)"
    call_name = str(user_name or "").strip()[:20]
    call_line = (
        f"사용자 호칭: {call_name}님 — 대화 시 '{call_name}님'으로 공손히 부릅니다.\n"
        if call_name
        else "사용자 호칭: (미정)\n"
    )

    prompt = (
        f"당신은 {WHICK_AI_NAME}입니다. {WHICK_AI_ROLE}.\n"
        f"{call_line}"
        f"현재 날씨/시간 정보: {weather_summary or '없음'}\n"
        f"로컬 라이브러리 곡 수: {int(library_count or 0)}\n"
        f"라이브러리 작곡가/아티스트: {catalog_line}\n"
        f"최근 대화:\n{hist_block}\n"
        f"사용자 메시지: {message}\n\n"
        "반드시 지킬 말투·행동 규칙:\n"
        "(A) 항상 공손한 존댓말(~습니다/~입니다). 반말 금지.\n"
        "(B) 작곡가·작품·제목이 보이면 intent=search 또는 play, "
        "search_query에 그 이름(가능하면 영어 통용명)을 넣는다. "
        "recommend로 보내지 말 것.\n"
        "(C) '추천해줘/아무거나'처럼 단서 없는 요청만 intent=recommend.\n"
        "(D) 기분·속어·분위기(꿀꿀, 화끈 등)만 있고 작곡가·장르·곡명이 없으면 "
        "intent=clarify, recommend=false, search_query=\"\", "
        "reply는 한 문장으로 검색 가능한 단어로 다시 말해 달라고 요청.\n"
        "(E) 날씨·정체·일상 대화만 intent=chat. "
        "호칭이 있으면 답변에 자연스럽게 한 번 정도만 사용.\n"
        "(F) search/play/recommend 성공 시 reply는 한 문장. "
        "곡 목록은 서버가 붙인다.\n"
        "의도:\n"
        "- chat: 인사·날씨·일반 대화\n"
        "- search: 특정 작곡가·작품·제목·장르 검색\n"
        "- recommend: 단서 없는 취향 추천만\n"
        "- play: 재생까지 원함(이름·장르가 있으면 search_query 필수)\n"
        "- clarify: 검색어로 못 옮기는 분위기 요청\n"
        "JSON만 출력:\n"
        '{"intent":"chat|search|recommend|play|clarify","reply":"...",'
        '"search_query":"","recommend":false,"play":false}'
    )
    try:
        async with httpx.AsyncClient(timeout=CHAT_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{url}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": ollama_generate_options(),
                },
            )
            if resp.status_code == 200:
                parsed = json.loads(resp.json().get("response") or "{}")
                if isinstance(parsed, dict) and str(parsed.get("reply") or "").strip():
                    intent = str(parsed.get("intent") or "chat").strip().lower()
                    if intent not in {"chat", "search", "recommend", "play", "clarify"}:
                        intent = "chat"
                    reply = str(parsed.get("reply") or "").strip()[:800]
                    search_query = str(parsed.get("search_query") or "").strip()[:120]
                    recommend = bool(parsed.get("recommend")) or intent == "recommend"
                    play = bool(parsed.get("play")) or intent == "play"

                    catalog_hit = match_catalog_in_message(message, uniq)
                    if catalog_hit:
                        intent = "play" if play else "search"
                        search_query = search_query or catalog_hit
                        recommend = False

                    if intent == "clarify" or (
                        _looks_like_music_request(message)
                        and not search_query
                        and not catalog_hit
                        and not _is_bare_recommend_request(message)
                        and intent in {"recommend", "chat"}
                    ):
                        intent = "clarify"
                        recommend = False
                        play = False
                        search_query = ""
                        reply = _unclear_music_reply()
                    elif _looks_like_music_request(message) and intent == "chat":
                        # 음악 요청인데 chat으로 빠지면 검색 시도 (맹목 추천 금지)
                        intent = "play" if play else "search"
                        search_query = search_query or message[:80]
                        recommend = False
                        reply = "라이브러리에서 찾아 보겠습니다."
                    elif intent in {"search", "recommend", "play"}:
                        ask_back = any(
                            x in reply
                            for x in (
                                "어떤",
                                "무슨",
                                "뭘",
                                "해줄까",
                                "드릴까요?",
                                "어때",
                                "뭐 할까",
                                "골라줄까",
                                "원하시",
                            )
                        )
                        clarify_ok = any(
                            x in reply for x in ("다시 말씀", "검색", "작곡가", "장르", "이해하지")
                        )
                        if (ask_back and not clarify_ok) or (len(reply) > 80 and not clarify_ok):
                            reply = "요청하신 곡을 골라 두었습니다."

                    return {
                        "intent": intent,
                        "reply": reply,
                        "search_query": search_query,
                        "recommend": recommend,
                        "play": play,
                    }, {**status, "used_url": url}
    except Exception as exc:
        print(f"[AI] chat {url}: {exc}")
    return fallback, status
