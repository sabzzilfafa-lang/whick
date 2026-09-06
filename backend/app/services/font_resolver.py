"""공통 폰트 해결 — Windows(맑은 고딕) 우선, 없으면 번들/시스템 Noto Sans KR.

배포 환경(고객 PC, 비-Windows)에서도 한글 렌더링이 깨지지 않도록
모든 PIL/ASS 폰트 선택은 이 모듈을 경유한다.
"""

from __future__ import annotations

import os
from pathlib import Path

# 번들 폰트 (backend/app/assets/fonts/ — Noto Sans KR, OFL 라이선스)
_BUNDLED_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

_BUNDLED = {
    "regular": "NotoSansKR-Regular.otf",
    "bold": "NotoSansKR-Bold.otf",
    "black": "NotoSansKR-Black.otf",
}

# Windows 계열 폰트 (존재할 때만 사용)
_WINDOWS = {
    "regular": ["C:/Windows/Fonts/malgun.ttf"],
    "bold": ["C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf"],
    "black": ["C:/Windows/Fonts/malgunbd.ttf"],
}

# 비-Windows 시스템 폰트 후보
_LINUX = {
    "regular": [
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ],
    "bold": [
        "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ],
    "black": [
        "/usr/share/fonts/truetype/noto/NotoSansKR-Black.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ],
}


def bundled_font_dir() -> Path:
    """번들 폰트 디렉터리 (ASS subtitles 필터의 fontsdir 옵션용)."""
    return _BUNDLED_FONT_DIR


def find_font_path(weight: str = "regular") -> Path | None:
    """weight: regular | bold | black. 사용 가능한 실제 폰트 파일 경로 반환."""
    weight = weight if weight in ("regular", "bold", "black") else "regular"
    table = _WINDOWS if os.name == "nt" else _LINUX
    candidates = list(table.get(weight, []))
    if os.name != "nt":
        candidates += _WINDOWS.get(weight, [])  # 리눅스에서도 Windows 경로에 있으면 사용
    # 1) 시스템 후보
    for c in candidates:
        p = Path(c)
        if p.is_file():
            return p
    # 2) 번들 폰트
    bundled = _BUNDLED_FONT_DIR / _BUNDLED[weight]
    if bundled.is_file():
        return bundled
    return None


def pil_font(size: int, *, bold: bool = False, black: bool = False):
    """PIL ImageFont — 실패 시 기본 폰트로 폴백 (절대 None 반환 안 함)."""
    from PIL import ImageFont

    weight = "black" if black else ("bold" if bold else "regular")
    path = find_font_path(weight)
    if path:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            pass
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def ass_font_name() -> str:
    """ASS Style에 쓸 폰트 패밀리명. fontsdir과 짝을 이룬다."""
    if os.name == "nt":
        return "Malgun Gothic"
    # 번들 Noto Sans KR을 쓰는 경우 — libass가 fontsdir에서 패밀리명으로 찾음
    return "Noto Sans KR"


def ass_fontsdir() -> str | None:
    """libass fontsdir — 번들 폰트 디렉터리 (존재할 때만)."""
    d = bundled_font_dir()
    if d.is_dir() and any(d.iterdir()):
        return d.resolve().as_posix().replace(":", "\\:")
    return None
