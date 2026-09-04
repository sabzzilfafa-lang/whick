# 2026-08-10: rust:1-bookworm / python:3.12-slim-bookworm (Debian) → ubuntu:26.04 통일
# 2026-08-10: librespot 빌드 제거 → 미리 컴파일된 바이너리 사용 (CPU 과열 방지)
FROM ubuntu:26.04

ARG CAMILLADSP_VERSION=2.0.3
ARG TARGETARCH=amd64

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-pip \
        mpd mpc ffmpeg curl ca-certificates libasound2t64 alsa-utils kmod \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /tmp/cdsp.tar.gz \
        "https://github.com/HEnquist/camilladsp/releases/download/v${CAMILLADSP_VERSION}/camilladsp-linux-${TARGETARCH}.tar.gz" \
    && tar -xzf /tmp/cdsp.tar.gz -C /usr/local/bin camilladsp \
    && chmod +x /usr/local/bin/camilladsp \
    && rm -f /tmp/cdsp.tar.gz

COPY remote/docker/librespot-bin /usr/local/bin/librespot
RUN chmod +x /usr/local/bin/librespot

WORKDIR /app

COPY remote/api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /app/api/requirements.txt

COPY remote/docker/gen_sweep_wav.py /app/docker/gen_sweep_wav.py
COPY remote/docker/log-sweep.wav /app/docker/log-sweep.wav
COPY remote/docker/test-left.wav /app/docker/test-left.wav
COPY remote/docker/test-right.wav /app/docker/test-right.wav
COPY remote/docker/camilla-pipe.sh /app/docker/camilla-pipe.sh
COPY remote/docker/whick-dsp-pipe.sh /app/docker/whick-dsp-pipe.sh
COPY remote/docker/ensure-aloop.sh /app/docker/ensure-aloop.sh
COPY remote/docker/start-camilla-daemon.sh /app/docker/start-camilla-daemon.sh
COPY remote/docker/camilla-fifo-bridge.py /app/docker/camilla-fifo-bridge.py
COPY remote/docker/whick-camilla-feed.sh /app/docker/whick-camilla-feed.sh
COPY remote/docker/resolve-alsa-device.sh /app/docker/resolve-alsa-device.sh
COPY remote/docker/whick-camilla-rate.sh /app/docker/whick-camilla-rate.sh
COPY remote/docker/gen_mpd_conf.py /app/docker/gen_mpd_conf.py
COPY remote/docker/spectrum_drain.py /app/docker/spectrum_drain.py
COPY remote/docker/librespot-camilla.sh /app/docker/librespot-camilla.sh
COPY remote/docker/start-librespot.sh /app/docker/start-librespot.sh
COPY remote/api /app/api
COPY remote/docker/entrypoint.sh /entrypoint.sh
COPY remote/docker/seed_demo_library.py /app/docker/seed_demo_library.py
# 판매 리모컨 UI SSOT — LAN http://IP/ 게스트 접속용 (trial/demo 와 독립)
COPY packages/remote /app/remote-ui

RUN chmod +x /entrypoint.sh /app/docker/camilla-pipe.sh /app/docker/whick-dsp-pipe.sh \
    /app/docker/ensure-aloop.sh /app/docker/start-camilla-daemon.sh \
    /app/docker/camilla-fifo-bridge.py /app/docker/whick-camilla-feed.sh \
    /app/docker/resolve-alsa-device.sh /app/docker/librespot-camilla.sh /app/docker/start-librespot.sh \
    /app/docker/whick-camilla-rate.sh /app/docker/spectrum_drain.py \
    && mkdir -p /var/lib/whick/library/music /var/lib/whick/library/playlists \
        /var/lib/whick/camilla /var/lib/whick/run /var/lib/whick/providers \
        /run/mpd \
    && rm -f /app/remote-ui/README.md

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
