#!/bin/sh
# CamillaDSP 상주 데몬 기동 (entrypoint / 수동)
set -eu
cd /app
python3 - <<'PY'
from api.audio_pipeline import ensure_default_profile
from api.camilla_daemon import start_daemon
from api.dsp_store import default_dsp_profile

ensure_default_profile()
r = start_daemon(profile=default_dsp_profile())
print("[start-camilla-daemon]", r)
raise SystemExit(0 if r.get("ok") else 1)
PY
