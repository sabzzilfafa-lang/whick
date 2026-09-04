"""ALSA /proc/asound 경로 헬퍼.

최신 runc(1.2+/1.3.x)는 컨테이너 rootfs 의 /proc 하위에 새 mountpoint 생성을
거부한다(CVE-2024-45310 완화). 따라서 호스트 /proc/asound 를 컨테이너
/proc/asound 로 bind 하면 컨테이너 기동이 실패한다.

대신 /proc 밖 경로(예: /run/whick/asound)로 bind 하고, ALSA proc 를 읽는
코드가 WHICK_ASOUND_ROOT 로 그 위치를 참조하게 한다. 기본값은 /proc/asound
이므로 privileged 컨테이너·호스트에서는 기존 동작을 그대로 유지한다.
"""
from __future__ import annotations

import os
from pathlib import Path


def asound_root() -> Path:
    return Path(os.environ.get("WHICK_ASOUND_ROOT", "/proc/asound"))
