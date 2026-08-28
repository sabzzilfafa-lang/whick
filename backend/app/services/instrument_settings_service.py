"""앨범 프리셋 기반 곡별 악기 세팅."""

from __future__ import annotations

import json
from typing import Any, Optional

from app.services.instrument_details import get_instrument_details

ROLE_LABELS = {
    "lead": "멜로디/리드",
    "rhythm": "리듬",
    "bass": "베이스",
    "harmony": "하모니",
    "texture": "텍스처",
    "effects": "효과",
}


def build_from_profile(profile: Optional[dict]) -> dict[str, Any]:
    if not profile:
        return {
            "preset_name": "",
            "mix_notes": "",
            "instruments": [],
        }

    items = get_instrument_details(
        {"id": "", "instruments": profile.get("instruments") or ""}
    )
    instruments = [
        {
            "name": item.get("name", ""),
            "name_en": item.get("name_en", ""),
            "role": item.get("role", "texture"),
            "tone": item.get("tone", ""),
            "texture": item.get("texture", ""),
            "notes": item.get("notes", ""),
            "from_preset": True,
        }
        for item in items
        if item.get("name")
    ]

    return {
        "preset_name": profile.get("name") or "",
        "mix_notes": profile.get("production_style") or "",
        "instruments": instruments,
    }


def _items_from_legacy(data: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    role_map = {
        "lead": "lead",
        "rhythm": "rhythm",
        "texture": "texture",
        "effects": "effects",
    }
    for key, role in role_map.items():
        raw = data.get(key)
        if not raw:
            continue
        names = raw if isinstance(raw, list) else [raw]
        for name in names:
            if not name:
                continue
            label = name if isinstance(name, str) else str(name)
            items.append(
                {
                    "name": label,
                    "name_en": label,
                    "role": role,
                    "tone": "",
                    "texture": "",
                    "notes": "",
                    "from_preset": False,
                }
            )
    return items


def parse_settings(raw: Optional[str]) -> Optional[dict[str, Any]]:
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    if isinstance(data.get("instruments"), list):
        return {
            "preset_name": data.get("preset_name") or "",
            "mix_notes": data.get("mix_notes") or "",
            "instruments": [
                {
                    "name": i.get("name", ""),
                    "name_en": i.get("name_en", i.get("name", "")),
                    "role": i.get("role", "texture"),
                    "tone": i.get("tone", ""),
                    "texture": i.get("texture", ""),
                    "notes": i.get("notes", ""),
                    "from_preset": bool(i.get("from_preset", False)),
                }
                for i in data["instruments"]
                if isinstance(i, dict) and i.get("name")
            ],
        }

    legacy_items = _items_from_legacy(data)
    if legacy_items:
        return {
            "preset_name": "",
            "mix_notes": data.get("mix_notes") or "",
            "instruments": legacy_items,
        }
    return None


def serialize_settings(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def ensure_settings(
    raw: Optional[str], profile: Optional[dict]
) -> dict[str, Any]:
    parsed = parse_settings(raw)
    if parsed and parsed.get("instruments"):
        return parsed
    return build_from_profile(profile)


def settings_summary(data: dict[str, Any]) -> str:
    names = [i["name"] for i in data.get("instruments", []) if i.get("name")]
    if not names:
        return "악기 없음"
    return ", ".join(names[:6]) + ("..." if len(names) > 6 else "")
