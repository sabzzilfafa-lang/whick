"""DAC 능력 프로필 — 최대 PCM/DSD · DoP 지원 (미니PC별 JSON)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# detect 전·DAC 미연결·probe 전 — 안전 바닥 (과장 192k/384k 금지)
# 어떤 DAC든 일단 소리 나게 하고, probe 후 한도 안에서만 올린다.
SAFE_FLOOR_RATE_HZ = int(os.getenv("WHICK_DAC_SAFE_FLOOR_RATE", "48000"))
SAFE_FLOOR_BITS = int(os.getenv("WHICK_DAC_SAFE_FLOOR_BITS", "16"))
CONSERVATIVE_CAPABILITY: dict[str, Any] = {
    "pcm_max_sample_rate": SAFE_FLOOR_RATE_HZ,
    "pcm_max_bit_depth": SAFE_FLOOR_BITS,
    "dsd_native": ["DSD64", "DSD128"],
    "dop": True,
    "source": "default",
    "notes": "DAC 미감지/미probe — 안전 바닥 48k",
}

# probe·USB DB로 확인된 뒤 상향 가능 (최대 768k)
PROBE_CEILING_RATE = int(os.getenv("WHICK_DAC_PROBE_MAX_SAMPLE_RATE", "768000"))


def capability_path() -> Path:
    return Path(os.getenv("WHICK_DAC_CAPABILITY", "/var/lib/whick/dac-capability.json"))


def load_dac_capability() -> dict[str, Any]:
    path = capability_path()
    if not path.is_file():
        return dict(CONSERVATIVE_CAPABILITY)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        out = dict(CONSERVATIVE_CAPABILITY)
        out.update({k: v for k, v in data.items() if v is not None})
        # 파일에 notes가 없으면(의도적 삭제) 기본 "미감지" 문구를 다시 붙이지 않음
        if "notes" not in data and (data.get("usb_vendor") or data.get("card_index") is not None):
            out.pop("notes", None)
        return out
    except (OSError, json.JSONDecodeError):
        return dict(CONSERVATIVE_CAPABILITY)


# 교체·미연결 시 이전 DAC identity가 남지 않도록 덮어쓰기 대상
_IDENTITY_KEYS = (
    "usb_vendor",
    "usb_product",
    "card_index",
    "card_id",
    "product_label",
    "label",
    "alsa_device",
    "probed_pcm_max_rate",
    "probed_pcm_max_bits",
    "probed_alsa_format",
    "probed_alsa_formats",
    "detected_at",
    "notes",
    "source",
)


def save_dac_capability(data: dict[str, Any]) -> dict[str, Any]:
    """현재 DAC 상태로 완전 덮어쓰기 (merge 금지 — 이전 DAC 잔존 방지)."""
    path = capability_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    out = dict(CONSERVATIVE_CAPABILITY)
    out.update({k: v for k, v in data.items() if v is not None})
    for key in _IDENTITY_KEYS:
        if key not in data or data.get(key) is None:
            out.pop(key, None)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def force_probed_alsa_format(fmt: str, *, reason: str = "") -> dict[str, Any]:
    """playback 포맷만 고정. capture(Loopback)에는 쓰지 않는다.

    source=probed 로 올리면서 rate 실측이 없으면 USB DB pcm_max(예: 768k)가
    effective_pcm_max_rate_hz 에 쓰여 OS 192k로 죽는다 → rate 미실측 시 안전 바닥.
    """
    cap = load_dac_capability()
    name = str(fmt or "").strip()
    if not name:
        return cap
    cap["probed_alsa_format"] = name
    bits = 32 if "32" in name else 16 if "16" in name else 24
    cap["pcm_max_bit_depth"] = bits
    cap["probed_pcm_max_bits"] = bits
    cap["source"] = "probed"
    # 포맷만 강제할 때 rate 실측 필드가 없으면 usb-db 과장 rate를 신뢰하지 않음
    if not cap.get("probed_pcm_max_rate"):
        cap["pcm_max_sample_rate"] = SAFE_FLOOR_RATE_HZ
        cap["probed_pcm_max_rate"] = SAFE_FLOOR_RATE_HZ
    if reason:
        cap["notes"] = reason
    else:
        cap.pop("notes", None)
    return save_dac_capability(cap)


def force_probed_bit_depth(bits: int, *, reason: str = "") -> dict[str, Any]:
    """camilladsp가 특정 bit depth로 재생 시작에 실패했을 때 강제 하향 저장.

    ALSA/USB 브릿지가 실칩 한계보다 높은 포맷을 '수락'해 놓고 실제로는
    camilladsp가 EINVAL로 죽는 경우(예: 16bit 실칩이 32bit로 오검출) 대비 —
    다음 재생부터는 이 값을 probed 값으로 신뢰해 동일 실패를 반복하지 않는다.
    identity(usb_vendor 등)는 유지하고 bit depth 관련 필드만 덮어쓴다.
    """
    cap = load_dac_capability()
    bits = max(16, min(32, int(bits)))
    cap["pcm_max_bit_depth"] = bits
    cap["probed_pcm_max_bits"] = bits
    cap["source"] = "probed"
    if reason:
        cap["notes"] = reason
    else:
        cap.pop("notes", None)
    return save_dac_capability(cap)


def effective_pcm_max_rate_hz() -> int:
    """재생 오픈에 쓸 PCM 상한 — probe 실측 우선, 없으면 안전 바닥.

    USB DB 과장 cap(예: 768k 표기·실측 48k)은 절대 신뢰하지 않는다.
    source=probed 여도 probed_pcm_max_rate 없으면 pcm_max_sample_rate(usb-db 잔존) 무시.
    """
    cap = load_dac_capability()
    probed = cap.get("probed_pcm_max_rate")
    if probed:
        try:
            return max(SAFE_FLOOR_RATE_HZ, int(probed))
        except (TypeError, ValueError):
            pass
    source = str(cap.get("source") or "")
    # rate 실측 필드가 있는 stream/probe 경로만 pcm_max 신뢰 (format-only force 제외)
    if source in ("alsa-stream", "alsa-probe", "probe"):
        try:
            return max(SAFE_FLOOR_RATE_HZ, int(cap.get("pcm_max_sample_rate") or SAFE_FLOOR_RATE_HZ))
        except (TypeError, ValueError):
            return SAFE_FLOOR_RATE_HZ
    return SAFE_FLOOR_RATE_HZ


def effective_pcm_max_bits() -> int:
    cap = load_dac_capability()
    probed = cap.get("probed_pcm_max_bits")
    if probed:
        try:
            return max(16, min(32, int(probed)))
        except (TypeError, ValueError):
            pass
    source = str(cap.get("source") or "")
    if source in ("alsa-stream", "alsa-probe", "probed", "probe"):
        try:
            return max(16, min(32, int(cap.get("pcm_max_bit_depth") or SAFE_FLOOR_BITS)))
        except (TypeError, ValueError):
            return SAFE_FLOOR_BITS
    return SAFE_FLOOR_BITS


def clamp_pcm_rate(sample_rate: int) -> int:
    return min(int(sample_rate), effective_pcm_max_rate_hz())


def pcm_exceeds_dac_cap(sample_rate: int) -> bool:
    return int(sample_rate) > clamp_pcm_rate(sample_rate)


def supports_dop() -> bool:
    return bool(load_dac_capability().get("dop", True))


def ensure_dac_capability_detected() -> dict[str, Any]:
    """파일 없거나 source=default 이면 감지."""
    from api.dac_detect import detect_dac_capability

    existing = load_dac_capability()
    path = capability_path()
    if not path.is_file() or existing.get("source") == "default":
        return detect_dac_capability(save=True)
    return existing
