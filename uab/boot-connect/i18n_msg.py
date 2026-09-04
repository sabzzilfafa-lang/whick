#!/usr/bin/env python3
"""고객용 설치 멘트 — 한글 위 · 영어 아래 (유선·무선 공통)."""
from __future__ import annotations


def bi(ko: str, en: str) -> str:
    """한글 한 줄(또는 여러 줄) 아래 영어."""
    k = (ko or "").strip()
    e = (en or "").strip()
    if not e:
        return k
    if not k:
        return e
    return f"{k}\n{e}"


def bi_join(pairs: list[tuple[str, str]], sep: str = "\n") -> str:
    """여러 (ko,en) 쌍을 블록으로 이어 붙임."""
    blocks = [bi(k, e) for k, e in pairs if (k or e)]
    return sep.join(blocks)
