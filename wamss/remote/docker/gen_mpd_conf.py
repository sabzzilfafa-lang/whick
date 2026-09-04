#!/usr/bin/env python3
"""MPD 설정 생성 — Camilla pipe · ALSA bit-perfect · null 출력."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# entrypoint: python3 /app/docker/gen_mpd_conf.py → sys.path[0]가 /app/docker 이므로 /app 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.mpd_conf import render
from api.alsa_device import resolve_direct_alsa_device, resolve_direct_mixer_type
from api.playback_config import sync_dsp_pipe_env
from api.playback_router import camilla_enabled


def main() -> int:
    enabled = camilla_enabled()
    layout = os.getenv("WHICK_PLAYBACK_LAYOUT", "modern")
    if os.getenv("WHICK_PLAYBACK_MODE", "auto").strip().lower() == "legacy":
        layout = "legacy"
    sync_dsp_pipe_env(None)
    out = os.getenv("WHICK_MPD_CONF", "/etc/mpd.conf")
    content = render(
        camilla=enabled,
        layout=layout,
        alsa_device=resolve_direct_alsa_device(),
        direct_mixer=resolve_direct_mixer_type(),
        profile=None,
    )
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(content)
    if layout == "modern" and enabled:
        mode = "modern-dual"
    elif enabled:
        mode = "camilla-pipe-legacy"
    else:
        mode = "null"
    print(f"[gen_mpd_conf] wrote {out} mode={mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
