"""DSP·룸보정 프로필 — 체험 listening.lib.php 포팅 (고객 단일 프로필)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg

from api.camilla_yaml import full_camilla_config, profile_to_camilla_yaml
from api.dac_preprocess import (
    dac_preprocess_enabled,
    ensure_fir_coefficient_files,
    resolve_dac_os_factor,
    dac_os_factor_info,
)

EQ_BAND_DEFS = [
    {"freq": 60, "q": 1.0},
    {"freq": 120, "q": 1.0},
    {"freq": 250, "q": 1.0},
    {"freq": 500, "q": 1.1},
    {"freq": 1000, "q": 1.0},
    {"freq": 2000, "q": 1.0},
    {"freq": 5000, "q": 0.9},
    {"freq": 10000, "q": 0.8},
]

PRESET_CATALOG = [
    {"slug": "neutral", "labelKo": "플랫", "description": "8밴드 플랫", "gains": [0, 0, 0, 0, 0, 0, 0, 0]},
    {"slug": "warm", "labelKo": "따뜻", "description": "저역·중저역 강조", "gains": [2.5, 2.2, 1.6, 1.0, 0.3, -0.8, -1.6, -2.4]},
    {"slug": "bright", "labelKo": "밝음", "description": "고역 강조", "gains": [-2.0, -1.4, -0.5, 0, 0.8, 1.6, 2.4, 3.0]},
    {"slug": "vocal", "labelKo": "보컬", "description": "1~5kHz 강조", "gains": [-1.5, -0.4, 1.0, 2.2, 2.8, 2.2, 1.2, -0.5]},
    {"slug": "wide", "labelKo": "와이드", "description": "공간감", "gains": [0.8, 0.5, 0, -0.3, 0, 0.5, 1.0, 1.2], "balance": {"left": 0.75, "right": 0.75}},
]

DEFAULT_PROFILE_KEY = "default"


def camilla_dir() -> Path:
    return Path(os.getenv("WHICK_CAMILLA_DIR", "/var/lib/whick/camilla"))


def camilla_profile_path() -> Path:
    return camilla_dir() / "profile.yml"


def merge_peaking(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for band in [*a, *b]:
        freq = int(band.get("freq") or 0)
        if freq <= 0:
            continue
        if freq not in merged:
            merged[freq] = {"freq": freq, "q": float(band.get("q") or 1), "gainDb": 0.0}
        merged[freq]["gainDb"] = max(-9.0, min(9.0, merged[freq]["gainDb"] + float(band.get("gainDb") or 0)))
    out = list(merged.values())
    out.sort(key=lambda x: x["freq"])
    return out


def user_peaking_for_room_save(dsp: dict[str, Any]) -> list[dict[str, Any]]:
    """Preserve user EQ when userPeaking was never split from legacy combined peaking."""
    explicit = dsp.get("userPeaking")
    if explicit:
        return list(explicit)
    if not dsp.get("eqEnabled"):
        return gains_to_peaking([0] * 8)
    combined = list(dsp.get("peaking") or gains_to_peaking([0] * 8))
    old_room = list(dsp.get("roomPeaking") or [])
    if not old_room:
        return combined
    room_gain = {int(b.get("freq") or 0): float(b.get("gainDb") or 0) for b in old_room}
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for band in combined:
        freq = int(band.get("freq") or 0)
        if freq <= 0:
            continue
        gain = max(-9.0, min(9.0, float(band.get("gainDb") or 0) - room_gain.get(freq, 0.0)))
        out.append({"freq": freq, "q": float(band.get("q") or 1), "gainDb": gain})
        seen.add(freq)
    for band in gains_to_peaking([0] * 8):
        if band["freq"] not in seen:
            out.append(band)
    out.sort(key=lambda x: x["freq"])
    return out


def gains_to_peaking(gains: list[float]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, definition in enumerate(EQ_BAND_DEFS):
        out.append(
            {
                "freq": definition["freq"],
                "q": definition["q"],
                "gainDb": float(gains[i] if i < len(gains) else 0),
            }
        )
    return out


def default_dsp_profile() -> dict[str, Any]:
    flat = gains_to_peaking([0] * 8)
    return {
        "enabled": True,
        "eqEnabled": False,
        "version": 2,
        "peaking": flat,
        "userPeaking": flat,
        "balanceDb": {"left": 0, "right": 0},
        "masterGainDb": 0.0,
        "swapChannels": False,
        "presetSlug": "neutral",
        "roomPeaking": [],
        "dacPreprocessEnabled": False,
        "dacOsFactorAuto": True,
        "dacOsFactor": 4,
        "dspPipeRateKhz": 48,
        "source": "default",
    }


def write_camilla_file(profile: dict[str, Any]) -> str:
    path = camilla_profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if dac_preprocess_enabled(profile):
        ensure_fir_coefficient_files(profile=profile)
    path.write_text(full_camilla_config(profile), encoding="utf-8")
    return str(path)


async def ensure_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dsp_profiles (
                profile_key   VARCHAR(64) PRIMARY KEY,
                preset_slug   VARCHAR(32),
                dsp_profile   JSONB NOT NULL,
                camilla_yaml  TEXT NOT NULL,
                updated_at    TIMESTAMPTZ DEFAULT now()
            )
            """
        )


async def get_profile(pool: asyncpg.Pool, profile_key: str = DEFAULT_PROFILE_KEY) -> dict[str, Any]:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT preset_slug, dsp_profile, camilla_yaml, updated_at FROM dsp_profiles WHERE profile_key = $1",
            profile_key,
        )
    if not row:
        profile = default_dsp_profile()
        return {
            "profileKey": profile_key,
            "presetSlug": profile["presetSlug"],
            "dsp": profile,
            "camillaYaml": full_camilla_config(profile),
            "camillaPath": None,
            "updatedAt": None,
            "dacOs": dac_os_factor_info(profile),
        }
    dsp = row["dsp_profile"]
    if isinstance(dsp, str):
        dsp = json.loads(dsp)
    return {
        "profileKey": profile_key,
        "presetSlug": row["preset_slug"],
        "dsp": dsp,
        "camillaYaml": row["camilla_yaml"],
        "camillaPath": str(camilla_profile_path()),
        "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None,
        "dacOs": dac_os_factor_info(dsp),
    }


async def save_profile(
    pool: asyncpg.Pool,
    dsp_profile: dict[str, Any],
    *,
    profile_key: str = DEFAULT_PROFILE_KEY,
    preset_slug: str | None = None,
) -> dict[str, Any]:
    await ensure_schema(pool)
    dsp_profile = dict(dsp_profile)
    if "enabled" not in dsp_profile:
        dsp_profile["enabled"] = True
    dsp_profile["updatedAt"] = datetime.now(timezone.utc).isoformat()
    if preset_slug:
        dsp_profile["presetSlug"] = preset_slug
    yaml = full_camilla_config(dsp_profile)
    camilla_path = write_camilla_file(dsp_profile)
    slug = preset_slug or dsp_profile.get("presetSlug") or "neutral"

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO dsp_profiles (profile_key, preset_slug, dsp_profile, camilla_yaml, updated_at)
            VALUES ($1, $2, $3::jsonb, $4, now())
            ON CONFLICT (profile_key) DO UPDATE SET
              preset_slug = EXCLUDED.preset_slug,
              dsp_profile = EXCLUDED.dsp_profile,
              camilla_yaml = EXCLUDED.camilla_yaml,
              updated_at = now()
            """,
            profile_key,
            slug,
            json.dumps(dsp_profile, ensure_ascii=False),
            yaml,
        )
    saved = await get_profile(pool, profile_key)
    saved["camillaPath"] = camilla_path
    return saved


async def save_room_correction(
    pool: asyncpg.Pool,
    peaking: list[dict[str, Any]],
    *,
    profile_key: str = DEFAULT_PROFILE_KEY,
) -> dict[str, Any]:
    existing = await get_profile(pool, profile_key)
    dsp = dict(existing.get("dsp") or default_dsp_profile())
    room_peaking = peaking or []
    # 이전 peaking 에 가산하면 재측정마다 컷이 쌓임 → userPeaking 과 새로 merge
    user_peaking = user_peaking_for_room_save(dsp)
    dsp["userPeaking"] = user_peaking
    dsp["roomPeaking"] = room_peaking
    if dsp.get("eqEnabled"):
        dsp["peaking"] = merge_peaking(room_peaking, user_peaking)
    else:
        dsp["peaking"] = list(room_peaking) if room_peaking else gains_to_peaking([0] * 8)
    dsp["source"] = "room-smartphone"
    return await save_profile(pool, dsp, profile_key=profile_key, preset_slug="neutral")


async def save_channel_setup(
    pool: asyncpg.Pool,
    *,
    swap_channels: bool,
    profile_key: str = DEFAULT_PROFILE_KEY,
) -> dict[str, Any]:
    existing = await get_profile(pool, profile_key)
    dsp = dict(existing.get("dsp") or default_dsp_profile())
    dsp["swapChannels"] = bool(swap_channels)
    dsp["source"] = "channel-setup"
    return await save_profile(pool, dsp, profile_key=profile_key)


async def save_user_eq(
    pool: asyncpg.Pool,
    *,
    eq_enabled: bool,
    gains: list[float] | None = None,
    balance_db: dict[str, float] | None = None,
    master_gain_db: float | None = None,
    dsp_enabled: bool | None = None,
    profile_key: str = DEFAULT_PROFILE_KEY,
) -> dict[str, Any]:
    existing = await get_profile(pool, profile_key)
    dsp = dict(existing.get("dsp") or default_dsp_profile())
    room_peaking = dsp.get("roomPeaking") or []
    if gains is not None:
        user_peaking = gains_to_peaking(gains)
    else:
        user_peaking = dsp.get("userPeaking") or gains_to_peaking([0] * 8)
    dsp["userPeaking"] = user_peaking
    dsp["eqEnabled"] = bool(eq_enabled)
    if eq_enabled:
        dsp["peaking"] = merge_peaking(room_peaking, user_peaking)
    else:
        dsp["peaking"] = list(room_peaking) if room_peaking else gains_to_peaking([0] * 8)
    if balance_db is not None:
        left = max(0.0, min(9.0, float(balance_db.get("left") or 0)))
        right = max(0.0, min(9.0, float(balance_db.get("right") or 0)))
        dsp["balanceDb"] = {"left": left, "right": right}
    if master_gain_db is not None:
        dsp["masterGainDb"] = max(-12.0, min(12.0, float(master_gain_db)))
    if dsp_enabled is not None:
        dsp["enabled"] = bool(dsp_enabled)
    dsp["source"] = "user-eq"
    return await save_profile(pool, dsp, profile_key=profile_key)


async def save_preset(
    pool: asyncpg.Pool,
    preset_slug: str,
    *,
    profile_key: str = DEFAULT_PROFILE_KEY,
) -> dict[str, Any]:
    preset = next((p for p in PRESET_CATALOG if p["slug"] == preset_slug), None)
    if not preset:
        raise ValueError("unknown preset")
    existing = await get_profile(pool, profile_key)
    existing_dsp = existing.get("dsp") or default_dsp_profile()
    room_peaking = existing_dsp.get("roomPeaking") or []
    swap_channels = bool(existing_dsp.get("swapChannels"))
    peaking = merge_peaking(room_peaking, gains_to_peaking(preset.get("gains") or []))
    balance = preset.get("balance") or {"left": 0, "right": 0}
    user_peaking = gains_to_peaking(preset.get("gains") or [])
    master_gain = float(existing_dsp.get("masterGainDb") or 0)
    return await save_profile(
        pool,
        {
            "enabled": True,
            "eqEnabled": True,
            "version": 2,
            "peaking": peaking,
            "userPeaking": user_peaking,
            "balanceDb": balance,
            "masterGainDb": max(-12.0, min(12.0, master_gain)),
            "swapChannels": swap_channels,
            "roomPeaking": room_peaking,
            "dacPreprocessEnabled": existing_dsp.get("dacPreprocessEnabled", False),
            "dacOsFactorAuto": existing_dsp.get("dacOsFactorAuto", True),
            "dacOsFactor": int(existing_dsp.get("dacOsFactor") or 4),
            "source": "preset",
            "presetSlug": preset_slug,
        },
        profile_key=profile_key,
        preset_slug=preset_slug,
    )


async def save_dac_preprocess(
    pool: asyncpg.Pool,
    enabled: bool,
    *,
    os_factor: int | None = None,
    os_factor_auto: bool | None = None,
    profile_key: str = DEFAULT_PROFILE_KEY,
) -> dict[str, Any]:
    existing = await get_profile(pool, profile_key)
    dsp = dict(existing.get("dsp") or default_dsp_profile())
    dsp["dacPreprocessEnabled"] = bool(enabled)
    if os_factor_auto is not None:
        dsp["dacOsFactorAuto"] = bool(os_factor_auto)
    if os_factor in (4, 8):
        dsp["dacOsFactor"] = int(os_factor)
    dsp["source"] = "dac-preprocess"
    saved = await save_profile(pool, dsp, profile_key=profile_key)
    saved["dacOs"] = dac_os_factor_info(dsp)
    return saved


async def save_dsp_pipe_rate(
    pool: asyncpg.Pool,
    rate_khz: int | float | str,
    *,
    profile_key: str = DEFAULT_PROFILE_KEY,
) -> dict[str, Any]:
    from api.playback_config import normalize_dsp_pipe_rate_khz

    khz = normalize_dsp_pipe_rate_khz(rate_khz)
    existing = await get_profile(pool, profile_key)
    dsp = dict(existing.get("dsp") or default_dsp_profile())
    dsp["dspPipeRateKhz"] = khz
    dsp["source"] = "dsp-pipe-rate"
    saved = await save_profile(pool, dsp, profile_key=profile_key)
    saved["dspPipeRateKhz"] = khz
    return saved
