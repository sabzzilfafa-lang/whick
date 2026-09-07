#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Read i18n_fix.py as base64 payload (written by local script), decode, run.
import base64
import re
import shutil
import subprocess
import json
import sys
from pathlib import Path

# The real fix script is embedded below as base64 (avoids transfer corruption)
PAYLOAD = Path("/tmp/i18n_fix.b64").read_text().strip()
code = base64.b64decode(PAYLOAD).decode("utf-8")
exec(compile(code, "i18n_fix_embedded", "exec"))
