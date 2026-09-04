"""AI 없이 DB 검색용 쿼리 확장 — 한글 별칭·오타·연관어.

검색 1차(즉시 응답)에서 Ollama를 부르지 않기 위한 SSOT.
분류로봇 search_keywords 와 함께 쓰며, AI는 DB miss·자연어일 때만.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable

# canon(검색에 쓸 영문/핵심어) → 한글·오타·별칭
# 값은 ILIKE/% 매칭·키워드 시드에 그대로 들어간다.
# 작품별 그룹은 분리 — 결혼(Figaro) ≠ 마술피리(Magic Flute).
_ALIAS_GROUPS: list[tuple[str, list[str]]] = [
    (
        "Beethoven",
        [
            "베토벤",
            "베토밴",
            "배도벤",
            "배도밴",
            "베도벤",
            "beethoven",
            "에그몬트",
            "egmont",
            "코리올란",
            "coriolan",
        ],
    ),
    (
        "Mozart",
        [
            "모차르트",
            "모짜르트",
            "모잘트",
            "mozart",
        ],
    ),
    (
        "Figaro",
        [
            "피가로",
            "figaro",
            "결혼",
            "marriage",
            "nozze",
            "le nozze",
        ],
    ),
    (
        "Magic Flute",
        [
            "마술피리",
            "magic flute",
            "zauberflote",
            "zauberflöte",
        ],
    ),
    (
        "Mendelssohn",
        [
            "멘델스존",
            "멘델스죤",
            "mendelssohn",
        ],
    ),
    (
        "Hebrides",
        [
            "핑갈",
            "핑갈의 동굴",
            "핑갈의동굴",
            "핑갈동굴",
            "동굴",  # 한글 단독 검색 (영문 제목만 있어도 키워드·별칭으로 매칭)
            "hebrides",
            "fingal",
            "fingal's cave",
            "fingals cave",
            "핑걸",
        ],
    ),
    (
        "Tchaikovsky",
        [
            "차이코프스키",
            "챠이코프스키",
            "차이콥스키",
            "tchaikovsky",
            "비창",
            "pathétique",
            "pathetique",
        ],
    ),
    (
        "Brahms",
        ["브람스", "브라암스", "brahms", "비극적", "tragic"],
    ),
    (
        "Grieg",
        ["그리그", "그리그이", "grieg", "피어귄트", "peer gynt", "아침"],
    ),
    (
        "Smetana",
        ["스메타나", "스메따나", "smetana", "블타바", "vltava", "몰다우", "내 조국"],
    ),
    (
        "Borodin",
        ["보로딘", "보로딘이", "borodin", "초원", "중앙아시아", "steppes"],
    ),
    # 연관·분위기 토큰 (시드/자연어 보조 — 단독으로는 약하게 매칭)
    (
        "winter night moon star",
        ["겨울", "밤", "달", "별", "눈", "밤하늘", "winter", "night", "moon", "star"],
    ),
]

_COMPOSER_CANONS = frozenset(
    {
        "Beethoven",
        "Mozart",
        "Mendelssohn",
        "Tchaikovsky",
        "Brahms",
        "Grieg",
        "Smetana",
        "Borodin",
    }
)

_GENERIC = {
    "music",
    "song",
    "songs",
    "track",
    "audio",
    "classical",
    "opera",
    "jazz",
    "pop",
    "rock",
    "음악",
    "클래식",
    "오페라",
    "재즈",
    "팝",
    "록",
    "orchestra",
    "오케스트라",
    "overture",
    "symphony",
    "서곡",
    "교향곡",
}

_NL_HINTS = re.compile(
    r"(어울리|듣고\s*싶|듣고싶|분위기|감성|추천|비\s*오|비오|퇴근|드라이브|"
    r"카페|새벽|집중|운동|잠\s*잘|잔잔|신나|슬픈|행복한|저녁에|아침에)",
    re.I,
)


def _norm(s: str) -> str:
    return " ".join((s or "").strip().split())


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.casefold(), b.casefold()).ratio()


def _variants_in_field(field: str, canon: str, variants: list[str]) -> list[str]:
    """field 문자열에 실제로 걸린 canon/variant만 반환 (그룹 전체 확장 금지)."""
    f = (field or "").casefold()
    if not f:
        return []
    hit: list[str] = []
    if canon.casefold() in f:
        hit.append(canon)
    for v in variants:
        if len(v) < 2:
            continue
        if v.casefold() in f:
            hit.append(v)
    return hit


def expand_query_aliases(query: str, *, fuzzy_min: float = 0.62) -> list[str]:
    """쿼리 → DB ILIKE용 키워드(원문 + 별칭 + 약한 오타 매칭)."""
    q = _norm(query)
    if not q:
        return []
    out: list[str] = [q]
    q_cf = q.casefold()
    q_compact = re.sub(r"\s+", "", q_cf)
    # 짧은 영문 토큰(art 등)이 별칭 부분문자열로 과확장되지 않게
    has_hangul = any("\uac00" <= ch <= "\ud7a3" for ch in q)
    min_sub_len = 2 if has_hangul else 3

    def _match_variant(v: str) -> bool:
        v_cf = v.casefold()
        v_compact = re.sub(r"\s+", "", v_cf)
        if _ratio(q, v) >= fuzzy_min:
            return True
        # 별칭이 쿼리에 포함 (베토벤 교향곡) — 안전
        if len(v_cf) >= min_sub_len and v_cf in q_cf:
            return True
        if len(v_compact) >= min_sub_len and v_compact in q_compact:
            return True
        # 쿼리가 별칭의 부분문자열 (오타 짧은 입력) — 영문 4자+, 한글 2자+만
        q_in_v_min = 2 if has_hangul else 4
        if len(q_cf) >= q_in_v_min and q_cf in v_cf:
            return True
        if len(q_compact) >= q_in_v_min and q_compact in v_compact:
            return True
        return False

    for canon, variants in _ALIAS_GROUPS:
        hit = any(_match_variant(v) for v in variants) or _match_variant(canon)
        if hit:
            out.append(canon)
            if canon in _COMPOSER_CANONS:
                out.extend(variants)
            else:
                for v in variants:
                    if _match_variant(v):
                        out.append(v)

    # 쉼표·조사 분해: "눈은 겨울, 밤은 달 별" → 토큰
    for part in re.split(r"[,/|·]|은|는|이|가|을|를|의", q):
        t = _norm(part)
        if len(t) >= 2:
            out.append(t)

    return _uniq_filter(out)


def seed_keywords_for_meta(title: str, composer: str = "", artist: str = "") -> str:
    """분류 AI 없을 때·시드용 — title/composer 각각 매칭, 그룹 전체 주입 금지."""
    title_s = str(title or "")
    comp_s = f"{composer or ''} {artist or ''}".strip()
    kws: list[str] = []

    for canon, variants in _ALIAS_GROUPS:
        if canon == "winter night moon star":
            continue

        from_title = _variants_in_field(title_s, canon, variants)
        from_comp = (
            _variants_in_field(comp_s, canon, variants) if canon in _COMPOSER_CANONS else []
        )

        if from_title:
            kws.extend(from_title)
            # 영문 제목만 있어도 한글 별칭·작품어를 search_keywords에 남긴다
            for v in variants:
                if any("\uac00" <= ch <= "\ud7a3" for ch in v):
                    kws.append(v)
                elif v.casefold() in title_s.casefold() or canon.casefold() in title_s.casefold():
                    kws.append(v)
        elif from_comp:
            kws.append(canon)
            for v in variants:
                if v.casefold() in comp_s.casefold():
                    kws.append(v)

        if len(kws) >= 12:
            break

    return " ".join(_uniq_filter(kws)[:10])


def looks_like_natural_language(query: str) -> bool:
    q = _norm(query)
    if len(q) >= 18:
        return True
    if _NL_HINTS.search(q):
        return True
    # 공백 많은 문장형
    if len(q.split()) >= 4 and any("\uac00" <= ch <= "\ud7a3" for ch in q):
        return True
    return False


def _uniq_filter(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        s = _norm(str(raw or ""))
        if len(s) < 2:
            continue
        if s.casefold() in _GENERIC:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def is_strong_db_hit(row_count: int, query: str, keywords: list[str]) -> bool:
    """1차 DB 결과를 바로 반환할지."""
    if row_count <= 0:
        return False
    # 자연어는 AI 의도 보강이 유리 — 단, 이미 여러 히트면 바로
    if looks_like_natural_language(query):
        return row_count >= 3
    return True
