"""미니PC 호스트 메트릭 — monitor · remote API · 관제 스냅샷 SSOT"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import time
from typing import Any

SSD1_MOUNT = os.getenv("WHICK_DISK_SSD1_MOUNT", "/")
SSD2_MOUNT = (os.getenv("WHICK_DISK_SSD2_MOUNT") or "/mnt/music").strip()
# 음원 파티션 후보 — /mnt/music 우선 (music 게이지 SSOT)
_SSD2_FALLBACKS = ("/mnt/music", "/var/lib/whick", "/whick-lab")
_MUSIC_DIR_CANDIDATES = (
    os.getenv("WHICK_MUSIC_DIR") or "/var/lib/whick/library/music",
    "/mnt/music",
)
NET_LINK_MBIT = float(os.getenv("WHICK_NET_LINK_MBIT", "1000") or "1000")
HEALTH_ALERT_STATE = os.getenv(
    "WHICK_HEALTH_ALERT_STATE", "/var/lib/whick/run/health-alert-state.json"
)

_prev_net: dict[str, float] | None = None
_last_net_pct = 0.0
_prev_cpu: dict[str, float] | None = None


def _mount_usable(mount: str) -> bool:
    if not mount:
        return False
    try:
        return os.path.isdir(mount) and os.path.ismount(mount)
    except OSError:
        return False


def disk_stats_for_mount(mount: str) -> dict[str, float | int | str] | None:
    """df -Pk → pct·total_kb·used_kb·avail_kb."""
    try:
        out = subprocess.run(
            ["df", "-Pk", mount],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        line = (out.stdout or "").strip().split("\n")[-1]
        parts = line.split()
        if len(parts) < 5:
            return None
        total_kb = int(parts[1])
        used_kb = int(parts[2])
        avail_kb = int(parts[3])
        pct = float(parts[4].replace("%", "") or 0)
        # 관제(monitor)·리모트 표시 통일 — 정수 %
        pct = float(int(round(pct)))
        if total_kb <= 0:
            return None
        return {
            "pct": pct,
            "total_kb": total_kb,
            "used_kb": used_kb,
            "avail_kb": avail_kb,
            "mount": mount,
        }
    except Exception:
        return None


def disk_pct_for_mount(mount: str) -> float | None:
    st = disk_stats_for_mount(mount)
    return float(st["pct"]) if st else None


def _same_filesystem(a: str, b: str) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return True


def resolve_ssd2_mount(ssd1: str = SSD1_MOUNT) -> str | None:
    """시스템(/)과 다른 음원 파티션 마운트 탐색."""
    candidates: list[str] = []
    if SSD2_MOUNT:
        candidates.append(SSD2_MOUNT)
    for m in _SSD2_FALLBACKS:
        if m not in candidates:
            candidates.append(m)
    for m in candidates:
        if not _mount_usable(m):
            continue
        if _same_filesystem(m, ssd1):
            continue
        return m
    return None


def directory_usage_pct(path: str) -> float | None:
    """별도 music 파티션이 없을 때 — 음원 디렉터리 점유율(해당 FS 전체 대비)."""
    if not path or not os.path.isdir(path):
        return None
    try:
        out = subprocess.run(
            ["du", "-sk", path],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        used_kb = int((out.stdout or "").strip().split()[0])
        if used_kb <= 0:
            return None
        st = disk_stats_for_mount(path)
        if not st or int(st["total_kb"]) <= 0:
            return None
        pct = int(round((used_kb / float(st["total_kb"])) * 100))
        if pct < 1:
            pct = 1
        return float(min(100, pct))
    except Exception:
        return None


def read_cpu_busy_pct() -> float | None:
    """CPU 사용률 — /proc/stat busy% (monitor metrics.mjs 와 동일 SSOT)."""
    global _prev_cpu
    try:
        line = open("/proc/stat", encoding="utf-8").readline()
        parts = [float(x) for x in line.split()[1:8]]
        if len(parts) < 4:
            return None
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)
        total = sum(parts)
        prev = _prev_cpu
        _prev_cpu = {"idle": idle, "total": total}
        if prev is None:
            return None
        td = total - float(prev["total"])
        id_ = idle - float(prev["idle"])
        if td <= 0:
            return None
        return max(0.0, min(100.0, round((1.0 - id_ / td) * 1000) / 10))
    except Exception:
        return None


def read_mem_pct() -> float | None:
    """메모리 사용률 — (total-freemem)/total 과 동일하게 free 기준이 아니라
    monitor(os.freemem)에 맞추려면 MemAvailable 대신 단순 used 비율을 쓴다.
    관제·리모트 통일: MemAvailable 기반 (체감 여유)."""
    try:
        meminfo = open("/proc/meminfo", encoding="utf-8").read()
        total = 0.0
        avail = 0.0
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                total = float(line.split()[1])
            elif line.startswith("MemAvailable:"):
                avail = float(line.split()[1])
        if total <= 0:
            return None
        return round(((total - avail) / total) * 100, 1)
    except Exception:
        return None


def read_temp_c() -> float | None:
    temps: list[float] = []
    for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        try:
            raw = int(open(path, encoding="utf-8").read().strip())
            if raw > 0:
                temps.append(raw / 1000.0)
        except (OSError, ValueError):
            continue
    if not temps:
        return None
    return round(max(temps), 1)


def _read_net_bytes() -> int:
    total = 0
    try:
        with open("/proc/net/dev", encoding="utf-8") as f:
            for line in f.read().splitlines()[2:]:
                parts = line.split()
                if len(parts) < 10:
                    continue
                iface = parts[0].rstrip(":")
                if not iface or iface == "lo" or iface.startswith(("veth", "br-", "docker")):
                    continue
                total += int(parts[1]) + int(parts[9])
    except OSError:
        return 0
    return total


def read_net_pct() -> float | None:
    global _prev_net, _last_net_pct
    try:
        bytes_now = _read_net_bytes()
        now = time.time()
        if _prev_net is None:
            time.sleep(0.25)
            bytes_now = _read_net_bytes()
            now = time.time()
            _prev_net = {"bytes": bytes_now, "at": now}
            return 0.0
        dt = now - float(_prev_net["at"])
        if dt < 0.05:
            return _last_net_pct
        rate = max(0.0, (bytes_now - float(_prev_net["bytes"])) / dt)
        _prev_net = {"bytes": bytes_now, "at": now}
        cap = (NET_LINK_MBIT * 1_000_000) / 8
        if cap <= 0:
            return 0.0
        pct = round((rate / cap) * 100)
        _last_net_pct = float(min(100, max(0, pct if pct > 0 else (1 if rate > 0 else 0))))
        return _last_net_pct
    except Exception:
        return None


def read_vram_metrics() -> dict[str, Any]:
    cmd = [
        "nvidia-smi",
        "--query-gpu=name,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
        line = (out.stdout or "").strip().split("\n")[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            return {"gpu_available": False}
        name, util, used, total = parts
        used_mb = int(float(used or 0))
        total_mb = int(float(total or 0))
        if total_mb <= 0:
            return {"gpu_available": False}
        pct = min(100, round((used_mb / total_mb) * 100))
        return {
            "gpu_available": True,
            "gpu_name": name,
            "gpu_util_pct": min(100, int(float(util or 0))),
            "vram_used_mb": used_mb,
            "vram_total_mb": total_mb,
            "vram_pct": pct,
            "vram_label": f"{used_mb / 1024:.1f}/{total_mb / 1024:.0f} GB",
        }
    except Exception:
        return {"gpu_available": False}


def read_health_alert_state() -> dict[str, Any]:
    try:
        with open(HEALTH_ALERT_STATE, encoding="utf-8") as handle:
            data = json.load(handle)
        return {
            "alerts": data.get("alerts") if isinstance(data.get("alerts"), list) else [],
            "updated_at": data.get("updated_at"),
            "ssd_hours": (data.get("metrics") or {}).get("ssd_hours"),
        }
    except (OSError, ValueError, TypeError):
        return {"alerts": [], "updated_at": None, "ssd_hours": None}


def collect_host_metrics() -> dict[str, Any]:
    cpu_pct = read_cpu_busy_pct()
    if cpu_pct is None:
        # 첫 샘플은 delta 없음 — 즉시 한 번 더
        time.sleep(0.15)
        cpu_pct = read_cpu_busy_pct()
    mem_pct = read_mem_pct()
    ssd1 = disk_stats_for_mount(SSD1_MOUNT)
    ssd2_mount = resolve_ssd2_mount(SSD1_MOUNT)
    ssd2 = disk_stats_for_mount(ssd2_mount) if ssd2_mount else None
    ssd1_pct = float(ssd1["pct"]) if ssd1 else None
    ssd2_pct = float(ssd2["pct"]) if ssd2 else None
    if ssd2 and int(ssd2.get("used_kb") or 0) > 0 and ssd2_pct == 0:
        ssd2_pct = 1.0
    if ssd2_pct is None:
        for path in _MUSIC_DIR_CANDIDATES:
            pct = directory_usage_pct(str(path))
            if pct is not None:
                ssd2_pct = pct
                ssd2_mount = str(path)
                break
    temp_c = read_temp_c()
    net_pct = read_net_pct()
    vram = read_vram_metrics()
    alert_state = read_health_alert_state()

    health = "normal"
    if (cpu_pct or 0) >= 90 or (mem_pct or 0) >= 92:
        health = "warning"
    if (ssd1_pct or 0) >= 92 or (ssd2_pct or 0) >= 92:
        health = "warning"

    metrics: dict[str, Any] = {
        "cpu_pct": cpu_pct,
        "mem_pct": mem_pct,
        "disk_pct": ssd1_pct,
        "ssd1_pct": ssd1_pct,
        "ssd2_pct": ssd2_pct,
        "ssd1_total_kb": int(ssd1["total_kb"]) if ssd1 else None,
        "ssd1_used_kb": int(ssd1["used_kb"]) if ssd1 else None,
        "ssd2_total_kb": int(ssd2["total_kb"]) if ssd2 else None,
        "ssd2_used_kb": int(ssd2["used_kb"]) if ssd2 else None,
        "ssd2_mount": ssd2_mount,
        "temp_c": temp_c,
        "net_pct": net_pct,
        "ssd_hours": alert_state.get("ssd_hours"),
    }
    if vram.get("gpu_available"):
        metrics.update(
            {
                "gpu_available": True,
                "vram_pct": vram.get("vram_pct"),
                "vram_label": vram.get("vram_label"),
                "gpu": vram,
            }
        )
    else:
        metrics["gpu_available"] = False

    return {
        "health": "warning" if alert_state["alerts"] else health,
        "metrics": metrics,
        "agent_online": True,
        "health_alerts": alert_state["alerts"],
        "health_alerts_updated_at": alert_state["updated_at"],
    }


def system_status_payload(uptime_sec: int | None = None) -> dict[str, Any]:
    row = collect_host_metrics()
    metrics = dict(row.get("metrics") or {})
    # 수명 판단에는 SSD SMART Power-On Hours만 사용한다.
    # OS uptime은 재부팅·재설치로 초기화되므로 누적시간으로 대체하지 않는다.
    metrics["operating_hours"] = metrics.get("ssd_hours")
    return {
        "ok": True,
        "agent_online": True,
        "health": row["health"],
        "uptime_sec": uptime_sec,
        "metrics": metrics,
        "health_alerts": row.get("health_alerts") or [],
        "health_alerts_updated_at": row.get("health_alerts_updated_at"),
        "source": "device",
    }
