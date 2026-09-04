"""Whick HWID — motherboard-only (CPU/RAM/SSD/LAN 교체와 무관)."""
from __future__ import annotations

import hashlib
import re
import subprocess
import time
from pathlib import Path

HW_ID_SCHEME = "motherboard-v1"
HW_ID_SCHEME_DEGRADED = "motherboard-v1-degraded"

DMI_CMD_TIMEOUT_SEC = 8.0

_DEGRADED_SOURCES = frozenset({"degraded", "fallback", "machine_id", "live_node"})

_INVALID_DMI = frozenset(
    s.lower()
    for s in (
        "",
        "none",
        "null",
        "n/a",
        "na",
        "not available",
        "not specified",
        "not set",
        "to be filled by o.e.m.",
        "default string",
        "system serial number",
        "chassis serial number",
        "123456789",
        "0123456789",
        "00000000-0000-0000-0000-000000000000",
    )
)


def _clean(value: str) -> str:
    s = re.sub(r"\s+", " ", str(value or "").strip())
    if s.lower() in _INVALID_DMI:
        return ""
    return s


def _clean_relaxed(value: str) -> str:
    """degraded tier — OEM placeholder만 제외."""
    s = re.sub(r"\s+", " ", str(value or "").strip())
    if not s or s.lower() in ("none", "null", "n/a", "na"):
        return ""
    return s


def _read_sysfs(name: str, *, relaxed: bool = False) -> str:
    try:
        raw = Path(f"/sys/class/dmi/id/{name}").read_text()
        return (_clean_relaxed if relaxed else _clean)(raw)
    except OSError:
        return ""


def _dmidecode(field: str) -> str:
    out = _run_dmidecode(["dmidecode", "-s", field])
    return _clean(out.splitlines()[0] if out else "")


def _dmidecode_table(type_id: int) -> dict[str, str]:
    """dmidecode -t N — Handle 블록 key: value 파싱."""
    out = _run_dmidecode(["dmidecode", "-t", str(type_id)])
    if not out:
        return {}

    out_map: dict[str, str] = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = _clean(val.strip())
        if key and val:
            out_map[key] = val
    return out_map


def _pick(*values: str) -> str:
    for v in values:
        if v:
            return v
    return ""


def _scheme_for_source(source: str) -> str:
    if source in _DEGRADED_SOURCES:
        return HW_ID_SCHEME_DEGRADED
    return HW_ID_SCHEME


def _clean_raw_for_server(source: str, raw: dict[str, str]) -> dict[str, str]:
    """서버 installMotherboardHwId.js 와 동일 필터 — raw 전송 전 usable 검사."""
    relaxed = _scheme_for_source(source) == HW_ID_SCHEME_DEGRADED
    out: dict[str, str] = {}
    for key, val in raw.items():
        if not val:
            continue
        cleaned = _clean_relaxed(val) if relaxed else _clean(val)
        if key == "uuid" and cleaned:
            cleaned = cleaned.lower()
        if cleaned:
            out[key] = cleaned
    return out


def _raw_usable_for_server(source: str, raw: dict[str, str]) -> bool:
    return bool(_clean_raw_for_server(source, raw))


def _run_dmidecode(args: list[str]) -> str:
    try:
        r = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=DMI_CMD_TIMEOUT_SEC,
        )
        if r.returncode != 0:
            return ""
        return r.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _read_sysfs_raw(name: str) -> str:
    try:
        return re.sub(r"\s+", " ", Path(f"/sys/class/dmi/id/{name}").read_text().strip())
    except OSError:
        return ""


def _dmidecode_raw(field: str) -> str:
    out = _run_dmidecode(["dmidecode", "-s", field])
    return re.sub(r"\s+", " ", (out.splitlines()[0] if out else "").strip())


def collect_motherboard_raw() -> dict[str, str]:
    """Raw DMI — 서버에서 OEM 필터·hash (SSOT)."""
    identity = {
        "manufacturer": _pick(
            _dmidecode_raw("baseboard-manufacturer"),
            _read_sysfs_raw("board_vendor"),
        ),
        "product": _pick(
            _dmidecode_raw("baseboard-product-name"),
            _read_sysfs_raw("board_name"),
        ),
        "serial": _pick(
            _dmidecode_raw("baseboard-serial-number"),
            _read_sysfs_raw("board_serial"),
        ),
        "version": _pick(
            _dmidecode_raw("baseboard-version"),
            _read_sysfs_raw("board_version"),
        ),
        "uuid": _pick(
            _dmidecode_raw("system-uuid"),
            _read_sysfs_raw("product_uuid"),
        ),
    }
    return {k: v for k, v in identity.items() if v}


def collect_baseboard_table_raw() -> dict[str, str]:
    out = _run_dmidecode(["dmidecode", "-t", "2"])
    if not out:
        return {}
    out_map: dict[str, str] = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = re.sub(r"\s+", " ", val.strip())
        if key and val:
            out_map[key] = val
    if not out_map:
        return {}
    identity = {
        "manufacturer": out_map.get("manufacturer", ""),
        "product": out_map.get("product name", "") or out_map.get("product", ""),
        "serial": out_map.get("serial number", ""),
        "version": out_map.get("version", ""),
    }
    return {k: v for k, v in identity.items() if v}


def collect_system_raw() -> dict[str, str]:
    identity = {
        "manufacturer": _pick(
            _dmidecode_raw("system-manufacturer"),
            _read_sysfs_raw("sys_vendor"),
        ),
        "product": _pick(
            _dmidecode_raw("system-product-name"),
            _read_sysfs_raw("product_name"),
        ),
        "serial": _pick(
            _dmidecode_raw("system-serial-number"),
            _read_sysfs_raw("product_serial"),
            _dmidecode_raw("chassis-serial-number"),
            _read_sysfs_raw("chassis_serial"),
        ),
        "uuid": _pick(
            _dmidecode_raw("system-uuid"),
            _read_sysfs_raw("product_uuid"),
        ),
    }
    return {k: v for k, v in identity.items() if v}


def collect_degraded_raw() -> dict[str, str]:
    fields = {
        "manufacturer": _pick(
            _read_sysfs_raw("board_vendor"),
            _read_sysfs_raw("sys_vendor"),
            _dmidecode_raw("bios-vendor"),
        ),
        "product": _pick(
            _read_sysfs_raw("board_name"),
            _read_sysfs_raw("product_name"),
        ),
        "serial": _pick(
            _read_sysfs_raw("board_serial"),
            _read_sysfs_raw("product_serial"),
            _read_sysfs_raw("chassis_serial"),
        ),
        "uuid": _pick(
            _read_sysfs_raw("product_uuid"),
            _dmidecode_raw("system-uuid"),
        ),
        "bios_version": _pick(
            _read_sysfs_raw("bios_version"),
            _dmidecode_raw("bios-version"),
        ),
    }
    return {k: v for k, v in fields.items() if v}


def collect_dmi_raw_for_server(
    *, retries: int = 6, retry_delay_sec: float = 2.0
) -> tuple[dict[str, str], str]:
    """
    Raw DMI only — hash는 서버 SSOT.
    @returns (motherboard_raw, identity_source)
    """
    collectors: tuple[tuple[str, object], ...] = (
        ("motherboard", collect_motherboard_raw),
        ("baseboard_table", collect_baseboard_table_raw),
        ("system", collect_system_raw),
        ("degraded", collect_degraded_raw),
    )

    for attempt in range(max(1, retries)):
        for source, fn in collectors:
            ident = fn()
            if ident and _raw_usable_for_server(source, ident):
                return ident, source
        if attempt + 1 < retries:
            time.sleep(retry_delay_sec)

    ident = collect_degraded_raw()
    if ident and _raw_usable_for_server("degraded", ident):
        return ident, "degraded"

    if not ident:
        for name in ("product_uuid", "board_name", "product_name", "sys_vendor"):
            v = _read_sysfs_raw(name)
            if v:
                ident = {"fallback": v}
                if _raw_usable_for_server("fallback", ident):
                    return ident, "fallback"
                ident = {}
                break

    if not ident:
        try:
            mid = Path("/etc/machine-id").read_text().strip()
        except OSError:
            mid = ""
        if mid and mid != "uninitialized":
            ident = {"machine_id": mid}
            if _raw_usable_for_server("machine_id", ident):
                return ident, "machine_id"

    ident = {"live_node": Path("/proc/sys/kernel/hostname").read_text().strip() or "whick-live"}
    if _raw_usable_for_server("live_node", ident):
        return ident, "live_node"

    return {}, "missing"


def collect_motherboard_identity() -> dict[str, str]:
    """Mainboard DMI — baseboard 우선."""
    manufacturer = _pick(
        _dmidecode("baseboard-manufacturer"),
        _read_sysfs("board_vendor"),
    )
    product = _pick(
        _dmidecode("baseboard-product-name"),
        _read_sysfs("board_name"),
    )
    serial = _pick(
        _dmidecode("baseboard-serial-number"),
        _read_sysfs("board_serial"),
    )
    version = _pick(
        _dmidecode("baseboard-version"),
        _read_sysfs("board_version"),
    )
    uuid = _pick(
        _dmidecode("system-uuid"),
        _read_sysfs("product_uuid"),
    )

    identity = {
        "manufacturer": manufacturer,
        "product": product,
        "serial": serial,
        "version": version,
        "uuid": uuid.lower() if uuid else "",
    }
    return {k: v for k, v in identity.items() if v}


def collect_baseboard_table_identity() -> dict[str, str]:
    """dmidecode -t 2 (Base Board Information)."""
    t2 = _dmidecode_table(2)
    if not t2:
        return {}
    identity = {
        "manufacturer": t2.get("manufacturer", ""),
        "product": t2.get("product name", "") or t2.get("product", ""),
        "serial": t2.get("serial number", ""),
        "version": t2.get("version", ""),
    }
    return {k: v for k, v in identity.items() if v}


def collect_system_identity() -> dict[str, str]:
    """보드 DMI 없을 때 — system/chassis (동일 본체 기준)."""
    manufacturer = _pick(
        _dmidecode("system-manufacturer"),
        _read_sysfs("sys_vendor"),
    )
    product = _pick(
        _dmidecode("system-product-name"),
        _read_sysfs("product_name"),
    )
    serial = _pick(
        _dmidecode("system-serial-number"),
        _read_sysfs("product_serial"),
        _dmidecode("chassis-serial-number"),
        _read_sysfs("chassis_serial"),
    )
    uuid = _pick(
        _dmidecode("system-uuid"),
        _read_sysfs("product_uuid"),
    )
    identity = {
        "manufacturer": manufacturer,
        "product": product,
        "serial": serial,
        "uuid": uuid.lower() if uuid else "",
    }
    return {k: v for k, v in identity.items() if v}


def collect_degraded_identity() -> dict[str, str]:
    """relaxed DMI — product_uuid·bios 등 남은 필드라도 사용."""
    fields = {
        "manufacturer": _pick(
            _read_sysfs("board_vendor", relaxed=True),
            _read_sysfs("sys_vendor", relaxed=True),
            _dmidecode("bios-vendor"),
        ),
        "product": _pick(
            _read_sysfs("board_name", relaxed=True),
            _read_sysfs("product_name", relaxed=True),
        ),
        "serial": _pick(
            _read_sysfs("board_serial", relaxed=True),
            _read_sysfs("product_serial", relaxed=True),
            _read_sysfs("chassis_serial", relaxed=True),
        ),
        "uuid": _pick(
            _read_sysfs("product_uuid", relaxed=True),
            _dmidecode("system-uuid"),
        ).lower(),
        "bios_version": _pick(
            _read_sysfs("bios_version", relaxed=True),
            _dmidecode("bios-version"),
        ),
    }
    return {k: v for k, v in fields.items() if v}


def compute_hw_id_hash(identity: dict[str, str], scheme: str = HW_ID_SCHEME) -> str:
    if not identity:
        raise RuntimeError("motherboard identity unavailable (no DMI fields)")

    parts = [scheme]
    for key in sorted(identity):
        parts.append(f"{key}={identity[key]}")
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_hw_identity(*, retries: int = 5, retry_delay_sec: float = 2.0) -> tuple[dict[str, str], str, str]:
    """
    HW ID — 여러 경로·재시도 후에도 실패하면 degraded tier 사용 (설치 중단 없음).
    @returns (identity, hw_id_hash, scheme)
    """
    collectors = (
        collect_motherboard_identity,
        collect_baseboard_table_identity,
        collect_system_identity,
        collect_degraded_identity,
    )

    for attempt in range(max(1, retries)):
        for fn in collectors:
            ident = fn()
            if ident:
                scheme = HW_ID_SCHEME if fn is not collect_degraded_identity else HW_ID_SCHEME_DEGRADED
                return ident, compute_hw_id_hash(ident, scheme), scheme
        if attempt + 1 < retries:
            time.sleep(retry_delay_sec)

    # 최후: sysfs raw 조합 (uuid 단독이라도)
    ident = collect_degraded_identity()
    if not ident:
        for name in ("product_uuid", "board_name", "product_name", "sys_vendor"):
            v = _read_sysfs(name, relaxed=True)
            if v:
                ident = {"fallback": v}
                break

    if not ident:
        # 설치 중단 방지 — Live 부팅마다 동일 apkovl machine fingerprint
        try:
            mid = Path("/etc/machine-id").read_text().strip()
        except OSError:
            mid = ""
        if mid and mid != "uninitialized":
            ident = {"machine_id": mid}
        else:
            ident = {"live_node": Path("/proc/sys/kernel/hostname").read_text().strip() or "whick-live"}

    return ident, compute_hw_id_hash(ident, HW_ID_SCHEME_DEGRADED), HW_ID_SCHEME_DEGRADED


def hw_id_hash() -> str:
    _, hw, _ = resolve_hw_identity()
    return hw


if __name__ == "__main__":
    import json

    ident, hw, scheme = resolve_hw_identity()
    print(
        json.dumps(
            {
                "hw_id_scheme": scheme,
                "motherboard": ident,
                "hw_id_hash": hw,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
