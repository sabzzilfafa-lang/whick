"""USB DAC 자동 감지 — ALSA hw_params · 알려진 제품 DB."""
from __future__ import annotations

import re
import subprocess
from typing import Any

from api.asound import asound_root
from api.dac_capability import CONSERVATIVE_CAPABILITY, PROBE_CEILING_RATE, save_dac_capability

# USB ID (vendor:product 소문자) → 능력 프로필 (실기·스펙 시트 기반 시드)
KNOWN_USB_DAC: dict[tuple[str, str], dict[str, Any]] = {
    ("0b05", "1778"): {"label": "AudioQuest DragonFly", "pcm_max_sample_rate": 96000, "pcm_max_bit_depth": 24, "dsd_native": ["DSD128"], "dop": True},
    ("0b05", "17eb"): {"label": "AudioQuest DragonFly Cobalt", "pcm_max_sample_rate": 96000, "pcm_max_bit_depth": 24, "dsd_native": ["DSD128"], "dop": True},
    ("20b1", "3009"): {"label": "iFi USB Audio", "pcm_max_sample_rate": 384000, "pcm_max_bit_depth": 32, "dsd_native": ["DSD512"], "dop": True},
    ("20b1", "0002"): {"label": "iFi Zen DAC", "pcm_max_sample_rate": 384000, "pcm_max_bit_depth": 32, "dsd_native": ["DSD512"], "dop": True},
    ("152a", "8878"): {"label": "Topping USB DAC", "pcm_max_sample_rate": 384000, "pcm_max_bit_depth": 32, "dsd_native": ["DSD512"], "dop": True},
    ("2d99", "b1f0"): {"label": "Topping E30/E50", "pcm_max_sample_rate": 384000, "pcm_max_bit_depth": 32, "dsd_native": ["DSD512"], "dop": True},
    ("249c", "f001"): {"label": "Schiit USB", "pcm_max_sample_rate": 384000, "pcm_max_bit_depth": 32, "dsd_native": ["DSD256"], "dop": True},
    ("0852", "c411"): {"label": "Cambridge Audio", "pcm_max_sample_rate": 384000, "pcm_max_bit_depth": 32, "dsd_native": ["DSD256"], "dop": True},
    # 라벨용 시드. 실측 SSOT=/proc/asound/card*/stream* · dump (PS100=S16 · 44.1/48k)
    ("8888", "1719"): {"label": "SMSL PS100", "pcm_max_sample_rate": 48000, "pcm_max_bit_depth": 16, "dsd_native": [], "dop": False},
}

PROBE_RATES = (44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000, 768000)
PROBE_FORMATS = ("S16_LE", "S24_LE", "S32_LE")


def _resolve_alsa_device() -> str:
    from api.alsa_device import resolve_direct_alsa_device

    return resolve_direct_alsa_device()


def _card_id_from_device(device: str) -> str | None:
    m = re.search(r"CARD=([^,\s]+)", device)
    return m.group(1) if m else None


def _card_index_from_id(card_id: str) -> int | None:
    cards = asound_root() / "cards"
    if not cards.is_file():
        return None
    for line in cards.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\s*(\d+)\s+\[([^\]]+)\]", line)
        if m and m.group(2).strip() == card_id:
            return int(m.group(1))
    return None


def _read_usb_id(card_index: int) -> tuple[str, str] | None:
    usbid = asound_root() / f"card{card_index}" / "usbid"
    if not usbid.is_file():
        return None
    raw = usbid.read_text(encoding="utf-8", errors="replace").strip().lower()
    if ":" not in raw:
        return None
    vendor, product = raw.split(":", 1)
    return vendor.strip(), product.strip()


def _read_card_name(card_index: int) -> str:
    for path in (asound_root() / f"card{card_index}" / "id",):
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace").strip()
    return f"card{card_index}"


def _probe_from_stream(card_index: int) -> tuple[int, int] | None:
    """ALSA stream 정보에서 rate/bit 추출 (aplay 재생 없이 즉시)."""
    root = asound_root() / f"card{card_index}"
    if not root.is_dir():
        return None
    max_rate = 0
    max_bits = 0
    for stream in sorted(root.glob("stream*")):
        try:
            text = stream.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"Rates:\s*([0-9,\s]+)", text, re.I):
            for tok in re.findall(r"\d+", m.group(1)):
                max_rate = max(max_rate, int(tok))
        for m in re.finditer(r"Bits:\s*([0-9,\s]+)", text, re.I):
            for tok in re.findall(r"\d+", m.group(1)):
                max_bits = max(max_bits, int(tok))
        # 예: Format: S32_LE
        for m in re.finditer(r"S(16|24|32)_LE", text):
            max_bits = max(max_bits, int(m.group(1)))
    if max_rate <= 0:
        return None
    return max_rate, max_bits or 24


def _hw_device_for_probe(device: str) -> str:
    """plug/plughw 는 소프트웨어 변환으로 S32가 통과할 수 있음 → hw: 만 실측."""
    d = (device or "").strip()
    if not d or d == "default":
        return d
    if d.startswith("hw:"):
        return d
    if d.startswith("plughw:"):
        return "hw:" + d[len("plughw:") :]
    if d.startswith("plug:"):
        return "hw:" + d[len("plug:") :]
    return d


_BIT_PROBE_RATE = 48000  # 거의 모든 DAC가 지원 — bit depth 확정에는 이 rate만 사용
_BIT_PROBE_FALLBACK_RATE = 192000  # 혹시 48k에서 특정 포맷이 안 열리면 대체 확인
# 2026-08-10: speaker-test -l 1 -s 1은 rate와 무관하게 성공 시 ~5초 소요(실측,
# Loopback 기준) — 기존 timeout=4는 "성공"도 강제 종료시켜 매번 예외로 삼켜지고
# 항상 aplay dump-hw-params(과장 가능한 값)로 폴백하게 만든 원인이었다.
# 실패(포맷 미지원 EINVAL)는 즉시 반환되므로 넉넉히 잡아도 최악 케이스엔 영향 적음.
_SPEAKER_TEST_TIMEOUT_SEC = 7.0


def _speaker_test_once(hw_device: str, fmt: str, rate: int, *, timeout: float = _SPEAKER_TEST_TIMEOUT_SEC) -> bool:
    try:
        proc = subprocess.run(
            [
                "speaker-test",
                "-D",
                hw_device,
                "-r",
                str(rate),
                "-c",
                "2",
                "-f",
                fmt,
                "-t",
                "sine",
                "-s",
                "1",
                "-l",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        combined = ((proc.stdout or "") + (proc.stderr or "")).lower()
        return proc.returncode == 0 and "error" not in combined and "invalid" not in combined
    except Exception:
        return False


def _probe_with_speaker_test(hw_device: str) -> tuple[int, int] | None:
    """hw: 실제 재생 시도로 rate/bit 상한 측정.

    USB 브릿지 stream 설명은 과장될 수 있음(예: PS100 16bit vs SU-1 32bit).
    stream/aplay dump-hw-params 만으로는 구분 실패 → speaker-test 로 검증.
    도구 없거나 전부 실패면 None (호출측 stream/보수값 폴백).

    2026-08-10 실측(Loopback 기준): speaker-test -l 1이 "성공"해도 ~5초 걸리는데
    기존 timeout=4였다 — 즉 성공 케이스조차 매번 타임아웃으로 죽어서 이 함수가
    사실상 항상 None을 반환했고, 호출측은 매번 덜 정확한 aplay dump-hw-params
    (USB 브릿지가 과장 보고 가능)로 폴백해왔다. 이게 "느린 인식·잘못된 bit
    강제"의 핵심 원인으로 보인다 — timeout을 7초로 늘려 성공 케이스를 실제로
    감지하게 한다. 실패(EINVAL)는 즉시 반환되므로 늘려도 최악 케이스 영향 적음.

    추가로 기존엔 3fmt×9rate=27회 전부 순회(최악 27×7≈189s)해서 느렸다.
    bit depth는 공용 rate(48000)에서만 먼저 확정(최대 3회)하고, 확정된 fmt로
    rate 상한만 탐색(최대 9회)해 실무 호출 수를 크게 줄인다. 최종 판정 로직
    (ALSA가 실제로 재생을 수락한 최고 포맷을 채택)은 그대로 유지.
    """
    if not hw_device or hw_device == "default":
        return None
    try:
        which = subprocess.run(
            ["sh", "-c", "command -v speaker-test"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if which.returncode != 0:
            return None
    except Exception:
        return None

    best_fmt = ""
    max_bits = 0
    probe_rate = _BIT_PROBE_RATE
    for fmt in reversed(PROBE_FORMATS):  # S32→S24→S16, 상위부터 확인해 성공 시 즉시 중단
        bits = 32 if fmt == "S32_LE" else 24 if fmt == "S24_LE" else 16
        if _speaker_test_once(hw_device, fmt, probe_rate):
            best_fmt = fmt
            max_bits = bits
            break
    if not best_fmt:
        # 드문 케이스: 특정 포맷이 48k에서 안 열리고 고레이트에서만 열리는 DAC
        # (ex. 구형 USB 브릿지의 S32_LE). fallback rate로 한 번만 재시도.
        probe_rate = _BIT_PROBE_FALLBACK_RATE
        for fmt in reversed(PROBE_FORMATS):
            bits = 32 if fmt == "S32_LE" else 24 if fmt == "S24_LE" else 16
            if _speaker_test_once(hw_device, fmt, probe_rate):
                best_fmt = fmt
                max_bits = bits
                break
    if not best_fmt:
        return None

    max_rate = 0
    for rate in reversed(PROBE_RATES):
        if rate == probe_rate:
            # bit depth 확정 단계에서 이미 이 rate로 성공 확인함 — 재검증 불필요
            max_rate = rate
            break
        if _speaker_test_once(hw_device, best_fmt, rate):
            max_rate = rate
            break
    if max_rate <= 0:
        max_rate = probe_rate

    if max_rate <= 0 or max_bits <= 0:
        return None
    return min(max_rate, PROBE_CEILING_RATE), max_bits


def _parse_dump_hw_params(text: str) -> tuple[int, int] | None:
    """aplay --dump-hw-params 출력에서 RATE/FORMAT 상한만 추출.

    dump는 요청 rate와 무관하게 RATE 라인을 찍으므로, returncode/RATE 문자열
    존재만으로 성공 판정하면 768k까지 잘못 채택된다. 구간/목록 파싱만 신뢰.
    """
    max_rate = 0
    max_bits = 0
    for m in re.finditer(r"RATE:\s*\[(\d+)\s+(\d+)\]", text, re.I):
        max_rate = max(max_rate, int(m.group(1)), int(m.group(2)))
    for m in re.finditer(r"RATE:\s*((?:\d+\s*)+)", text, re.I):
        for tok in re.findall(r"\d+", m.group(1)):
            max_rate = max(max_rate, int(tok))
    for m in re.finditer(r"FORMAT:\s*([^\n]+)", text, re.I):
        for bm in re.finditer(r"S(16|24|32)", m.group(1)):
            max_bits = max(max_bits, int(bm.group(1)))
    if max_rate <= 0:
        return None
    return min(max_rate, PROBE_CEILING_RATE), max(16, max_bits or 16)


def _probe_pcm_rates(device: str, card_index: int | None = None) -> tuple[int, int]:
    """지원 rate/bit 추정.

    1) /proc/asound stream Rates/Bits (USB altset 실목록 — PS100=48k/16)
    2) speaker-test(hw:) — stream 없거나 과장 의 때 실재생 검증
    3) aplay dump-hw-params — RATE 구간 파싱만 (요청 rate 성공 오판 금지)
    """
    max_rate = int(CONSERVATIVE_CAPABILITY["pcm_max_sample_rate"])
    max_bits = int(CONSERVATIVE_CAPABILITY["pcm_max_bit_depth"])  # 16 바닥

    hw_device = _hw_device_for_probe(device)

    # USB stream altset 목록이 있으면 rate/bit SSOT (브릿지 과장 적은 full-speed 장치)
    if card_index is not None:
        fast = _probe_from_stream(card_index)
        if fast:
            r = min(fast[0], PROBE_CEILING_RATE)
            b = max(16, min(int(fast[1] or 16), 32))
            # stream Bits가 16이면 speaker-test로 더 높은 bit를 채택하지 않음
            if b <= 16 or r <= 48000:
                return r, b
            # stream이 고비트/고레이트를 광고하면 speaker-test로 검증
            hw_probe = _probe_with_speaker_test(hw_device)
            if hw_probe:
                # rate는 stream과 speaker-test 중 보수(min), bits도 min
                return min(r, hw_probe[0]), min(b, hw_probe[1])
            return r, min(b, 24)

    hw_probe = _probe_with_speaker_test(hw_device)
    if hw_probe:
        return hw_probe

    if not device or device == "default":
        return max_rate, max_bits
    # dump 한 번(S16@48k)으로 RATE/FORMAT 구간만 파싱 — rate 순회 오판 제거
    try:
        proc = subprocess.run(
            [
                "aplay",
                "-D",
                hw_device if hw_device else device,
                "--dump-hw-params",
                "-f",
                "S16_LE",
                "-r",
                "48000",
                "-c",
                "2",
                "-d",
                "1",
                "/dev/zero",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        parsed = _parse_dump_hw_params((proc.stdout or "") + (proc.stderr or ""))
        if parsed:
            return parsed
    except Exception:
        pass
    return max_rate, max_bits


def detect_dac_capability(*, save: bool = True, probe: bool = True) -> dict[str, Any]:
    """USB DAC identity 즉시 반영. probe=False 면 능력 측정 생략(핫플러그 즉시 경로)."""
    device = _resolve_alsa_device()
    card_id = _card_id_from_device(device)
    card_index = _card_index_from_id(card_id) if card_id else None

    result: dict[str, Any] = {
        **CONSERVATIVE_CAPABILITY,
        "source": "auto-detect",
        "alsa_device": device,
        "detected_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }

    if card_index is None and device in ("default", ""):
        result["notes"] = "DAC 미연결 — USB 연결 후 detect"
        result["alsa_device"] = device or "default"
        # identity 필드는 넣지 않음 → save 시 이전 DAC 잔존 삭제
        if save:
            save_dac_capability(result)
        return result

    if card_index is not None:
        result["card_index"] = card_index
        result["card_id"] = _read_card_name(card_index)
        usb = _read_usb_id(card_index)
        if usb:
            result["usb_vendor"] = usb[0]
            result["usb_product"] = usb[1]
            known = KNOWN_USB_DAC.get(usb)
            if known:
                result.update({k: v for k, v in known.items() if k != "label"})
                result["product_label"] = known.get("label", "")
                result["source"] = "usb-db"

    if not probe:
        result["notes"] = "identity only — capability probe pending"
        if save:
            save_dac_capability(result)
        return result

    probed_rate, probed_bits = _probe_pcm_rates(device, card_index)
    probed_rate = min(probed_rate, PROBE_CEILING_RATE)
    db_max = int(result.get("pcm_max_sample_rate") or 0)
    db_bits = int(result.get("pcm_max_bit_depth") or 0)
    # USB DB는 라벨·대략 한도 시드. 오픈 포맷·실측 rate는 probe가 SSOT.
    if probed_rate > 0:
        result["pcm_max_sample_rate"] = min(db_max, probed_rate) if db_max else probed_rate
        result["probed_pcm_max_rate"] = min(db_max, probed_rate) if db_max else probed_rate
    else:
        result["probed_pcm_max_rate"] = probed_rate
    if probed_bits > 0:
        result["pcm_max_bit_depth"] = min(db_bits, probed_bits) if db_bits else probed_bits
        result["probed_pcm_max_bits"] = min(db_bits, probed_bits) if db_bits else probed_bits
    else:
        result["probed_pcm_max_bits"] = probed_bits
    result["source"] = "probed"
    try:
        from api.alsa_device import list_playback_camilla_formats

        fmts = list_playback_camilla_formats(device)
        if fmts:
            result["probed_alsa_format"] = fmts[0]
            result["probed_alsa_formats"] = fmts
    except Exception:
        pass
    result.pop("notes", None)

    if save:
        save_dac_capability(result)
    return result
