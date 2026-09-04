#!/usr/bin/env python3
"""Write the minimum host hardware health facts consumed by whick-monitor."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(os.getenv("WHICK_HARDWARE_HEALTH_OUT", "/var/lib/whick/run/hardware-health.json"))


def run(*args: str) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=15, check=False)
    return (proc.stdout or "").strip()


def root_disk() -> str | None:
    source = run("findmnt", "-n", "-o", "SOURCE", "/")
    if not source.startswith("/dev/"):
        return None
    parent = run("lsblk", "-n", "-o", "PKNAME", source).splitlines()
    if parent and parent[0].strip():
        return f"/dev/{parent[0].strip()}"
    return source


def cpu_model() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith(("model name", "hardware")) and ":" in line:
                return line.split(":", 1)[1].strip() or None
    except OSError:
        pass
    return None


def smart_facts(device: str | None) -> dict:
    if not device:
        return {"smart_status": "device_unavailable"}
    try:
        raw = run("smartctl", "-j", "-a", device)
        data = json.loads(raw)
    except (FileNotFoundError, json.JSONDecodeError, subprocess.SubprocessError):
        return {"smart_status": "smartctl_unavailable", "ssd_device": device}

    hours = (data.get("power_on_time") or {}).get("hours")
    if hours is None:
        for attr in (data.get("ata_smart_attributes") or {}).get("table") or []:
            if attr.get("id") == 9 or str(attr.get("name", "")).lower() == "power_on_hours":
                hours = (attr.get("raw") or {}).get("value")
                break
    passed = (data.get("smart_status") or {}).get("passed")
    return {
        "ssd_device": device,
        "ssd_model": data.get("model_name") or data.get("model_number"),
        "ssd_serial": data.get("serial_number"),
        "ssd_hours": int(hours) if isinstance(hours, (int, float)) else None,
        "smart_status": "passed" if passed is True else "failed" if passed is False else "unknown",
    }


def main() -> None:
    payload = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "cpu_model": cpu_model(),
        **smart_facts(root_disk()),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".hardware-health-", dir=OUT.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, OUT)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


if __name__ == "__main__":
    main()
