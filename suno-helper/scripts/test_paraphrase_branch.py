# -*- coding: utf-8 -*-
"""의역/재생성 분기 유닛 테스트 — DB 없이 로직만 검증."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


class FakeSong:
    def __init__(self, ko="", en="", lyrics=""):
        self.lyrics_ko = ko
        self.lyrics_en = en
        self.lyrics = lyrics or ko
        self.title = "t"
        self.title_en = None


from app.services.song_lyrics import lyrics_ko_text  # noqa: E402

PASS = []
FAIL = []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name)


# --- 백엔드 분기 규칙 시뮬 (api_generate_lyrics의 조건식 재현) ---
def branch_ko(song, req_ko_en_passed):
    ko_exists = bool((lyrics_ko_text(song) or "").strip())
    en = (req_ko_en_passed or "").strip() or (song.lyrics_en or "").strip()
    if en and not ko_exists:
        return "paraphrase"
    return "regenerate"


def branch_en(song, req_lyrics_ko_passed):
    already_en = bool((song.lyrics_en or "").strip())
    ko = (req_lyrics_ko_passed or "").strip() or (lyrics_ko_text(song) or "").strip()
    if ko and not already_en:
        return "paraphrase"
    return "regenerate"


# 시나리오 1: 영어로 먼저 생성, 한글 없음 → 한글 탭 생성 = 의역
s = FakeSong(en="Hello world")
check("ko tab, empty ko + en exists => paraphrase", branch_ko(s, None) == "paraphrase")

# 시나리오 2: 한·영 모두 존재 → 한글 탭 생성 = 재생성 (의역 아님) ← 이번 버그
s = FakeSong(ko="안녕 세상", en="Hello world")
check("ko tab, ko exists + en exists => regenerate", branch_ko(s, None) == "regenerate")

# 시나리오 3: 한글 먼저 생성, 영어 없음 → 영어 탭 = 의역
s = FakeSong(ko="안녕 세상")
check("en tab, empty en + ko exists => paraphrase", branch_en(s, None) == "paraphrase")

# 시나리오 4: 양쪽 모두 존재 → 영어 탭 = 재생성 ← 이번 버그
s = FakeSong(ko="안녕 세상", en="Hello world")
check("en tab, en exists + ko exists => regenerate", branch_en(s, None) == "regenerate")

# 시나리오 5: 둘 다 없음 → 새로 생성 경로
s = FakeSong()
check("en tab, nothing => regenerate(new)", branch_en(s, None) == "regenerate")

print()
print("ALL_OK" if not FAIL else f"FAILED: {FAIL}")
sys.exit(1 if FAIL else 0)
