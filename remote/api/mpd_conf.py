"""MPD 설정 생성 — Camilla Feed(Loopback) · DSD Direct · spectrum tap."""
from __future__ import annotations

import os
from typing import Any

from api.alsa_device import resolve_direct_alsa_device, resolve_direct_mixer_type
from api.dac_capability import supports_dop


def _spectrum_format() -> str:
    rate = int(os.getenv("WHICK_SPECTRUM_PIPE_RATE", "48000"))
    return f"{rate}:16:2"


def _camilla_feed_device() -> str:
    from api.camilla_loopback import loopback_feed_device

    return loopback_feed_device()


def _camilla_feed_format() -> str:
    from api.camilla_loopback import loop_mpd_format

    return loop_mpd_format()


def render(
    *,
    camilla: bool,
    layout: str = "modern",
    alsa_device: str | None = None,
    direct_mixer: str | None = None,
    profile: dict[str, Any] | None = None,
) -> str:
    direct_dev = alsa_device or resolve_direct_alsa_device()
    mixer = direct_mixer or resolve_direct_mixer_type()
    lines = [
        "# Whick player MPD — generated",
        'music_directory         "/var/lib/whick/library/music"',
        'playlist_directory      "/var/lib/whick/library/playlists"',
        'db_file                 "/var/lib/whick/library/mpd.db"',
        'log_file                "/var/lib/whick/library/mpd.log"',
        'pid_file                "/run/mpd/pid"',
        'state_file              "/var/lib/whick/library/mpdstate"',
        'auto_update             "yes"',
        'follow_outside_symlinks "yes"',
        'restore_paused          "yes"',
        'replaygain              "off"',
        "",
        'user                    "root"',
        'bind_to_address         "127.0.0.1"',
        'port                    "6600"',
        # 8 MB decode buffer — hi-res/CPU spike 시 underrun 완화 (기본 4 MB)
        'audio_buffer_size       "8192"',
        'max_connections         "20"',
        'max_playlist_length    "16384"',
        "",
    ]

    if layout == "modern" and camilla:
        dop_line = '    dop                 "1"' if supports_dop() else '    dop                 "0"'
        feed_fmt = _camilla_feed_format()
        from api.camilla_loopback import transport_mode

        mode = transport_mode()
        lines.extend(
            [
                # DSD DoP 등 — Camilla 우회가 필요할 때만 enable
                "audio_output {",
                '    type                "alsa"',
                '    name                "Whick Direct"',
                f'    device              "{direct_dev}"',
                f'    mixer_type          "{mixer}"',
                dop_line,
                # Camilla loopback: 0.5s buffer / 0.1s period (20ms period broke ALSA open on #49)
                '    buffer_time         "500000"',
                '    period_time         "100000"',
                '    auto_resample       "no"',
                '    auto_format         "yes"',
                '    auto_channels       "no"',
                '    enabled             "no"',
                "}",
                "",
            ]
        )
        if mode == "aloop":
            feed_dev = _camilla_feed_device()
            lines.extend(
                [
                    "audio_output {",
                    '    type                "alsa"',
                    '    name                "Whick DSP"',
                    f'    device              "{feed_dev}"',
                    f'    format              "{feed_fmt}"',
                    '    mixer_type          "software"',
                    '    buffer_time         "500000"',
                    '    period_time         "100000"',
                    '    auto_resample       "yes"',
                    '    auto_format         "yes"',
                    '    auto_channels       "no"',
                    '    enabled             "yes"',
                    "}",
                    "",
                ]
            )
        else:
            # fifo 상주 — MPD pipe → FIFO → bridge → Camilla
            lines.extend(
                [
                    "audio_output {",
                    '    type                "pipe"',
                    '    name                "Whick DSP"',
                    '    command             "/app/docker/whick-camilla-feed.sh"',
                    f'    format              "{feed_fmt}"',
                    '    mixer_type          "software"',
                    '    enabled             "yes"',
                    "}",
                    "",
                ]
            )
    elif camilla:
        lines.extend(
            [
                "audio_output {",
                '    type                "pipe"',
                '    name                "Whick CamillaDSP"',
                '    command             "/app/docker/camilla-pipe.sh"',
                '    format              "44100:16:2"',
                '    mixer_type          "software"',
                '    enabled             "yes"',
                "}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "audio_output {",
                '    type                "null"',
                '    name                "Whick PoC null output"',
                "}",
                "",
            ]
        )

    lines.extend(
        [
            "audio_output {",
            '    type                "fifo"',
            '    name                "Whick spectrum tap"',
            '    path                "/var/lib/whick/run/mpd-spectrum.pcm"',
            f'    format              "{_spectrum_format()}"',
            '    enabled             "yes"',
            "}",
            "",
        ]
    )
    return "\n".join(lines)
