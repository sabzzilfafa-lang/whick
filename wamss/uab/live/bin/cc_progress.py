#!/usr/bin/env python3
"""Report install phase progress to CC (bootstrap token from state file)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# cc_client lookup: phase-bundle bin/ · boot-connect on USB · env override
_BC_CANDIDATES = [
    Path(__file__).resolve().parent,  # live/bin/cc_client.py (bundle)
    Path(__file__).resolve().parent.parent,  # live/ (legacy)
]
_boot = os.environ.get("WHICK_BOOT_CONNECT_ROOT", "").strip()
if _boot:
    _BC_CANDIDATES.insert(0, Path(_boot))
for _root in _BC_CANDIDATES:
    if (_root / "cc_client.py").is_file() and str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
        break

try:
    from cc_client import patch_session_progress
except ImportError:
    patch_session_progress = None  # type: ignore


def _patch_session_progress_inline(
    token: str,
    session_id: int,
    *,
    phase: str = "",
    progress_pct: int | None = None,
    phase_progress_pct: int | None = None,
    progress_msg: str = "",
) -> None:
    """stdlib fallback when cc_client not on bundle path."""
    import json
    import urllib.request

    cc_url = os.environ.get("WHICK_CC_API_URL", "https://admin.whick.org/api/v1").rstrip("/")
    inner: dict = {}
    if phase:
        inner["phase"] = phase
    if progress_pct is not None:
        inner["progress_pct"] = progress_pct
    if phase_progress_pct is not None:
        inner["phase_progress_pct"] = phase_progress_pct
    if progress_msg:
        inner["progress_msg"] = progress_msg[:255]
    body = json.dumps({"type": "install_progress", "payload": inner}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        f"{cc_url}/install/sessions/{session_id}/progress",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Whick-cc_progress/1.0",
        },
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def load_credentials() -> tuple[str, int]:
    for key in (
        "WHICK_UAB_STATE",
        "WHICK_BOOTSTRAP_SESSION",
        "WHICK_SETUP_STATE",
    ):
        p = Path(os.environ.get(key, ""))
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        token = str(data.get("bootstrap_token") or "").strip()
        sid = data.get("session_id")
        if token and sid:
            return token, int(sid)
    # USB Live RAM filesystem fallback
    state = Path(os.environ.get("WHICK_SETUP_STATE", "/tmp/whick-setup-state.json"))
    boot = Path(os.environ.get("WHICK_BOOTSTRAP_SESSION", "/tmp/whick-bootstrap-session.json"))
    # SSD Ubuntu firstboot fallback
    ssd_boot = Path("/var/lib/whick/bootstrap-session.json")
    for p in (state, boot, ssd_boot):
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        token = str(data.get("bootstrap_token") or "").strip()
        sid = data.get("session_id")
        if token and sid:
            return token, int(sid)
    return "", 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--pct", type=int, default=None)
    ap.add_argument("--msg", default="")
    args = ap.parse_args()

    token, sid = load_credentials()
    if not token or not sid:
        print(f"[cc_progress] skip phase={args.phase} (no session)", file=sys.stderr)
        return
    if patch_session_progress:
        patch_session_progress(
            token,
            sid,
            phase=args.phase,
            phase_progress_pct=args.pct,
            progress_msg=args.msg[:255],
        )
    else:
        _patch_session_progress_inline(
            token,
            sid,
            phase=args.phase,
            phase_progress_pct=args.pct,
            progress_msg=args.msg[:255],
        )
    print(f"[cc_progress] {args.phase} {args.pct}% {args.msg}")


if __name__ == "__main__":
    main()
