#!/bin/sh
# MPD pipe → Camilla FIFO (상주 데몬 stdin 브리지)
set -eu
FIFO="${WHICK_CAMILLA_FIFO:-/var/lib/whick/run/camilla-in.pcm}"
mkdir -p "$(dirname "$FIFO")"
if [ ! -p "$FIFO" ]; then
  rm -f "$FIFO"
  mkfifo "$FIFO"
  chmod 666 "$FIFO" || true
fi
# stdin(PCM s32le) → FIFO. MPD가 출력을 끄면 cat 종료 → 브리지가 다음 open 대기.
# camilladsp 재시작 등으로 리더(bridge)가 잠깐 사라지면 cat이 EPIPE로 죽는데,
# exec로 끝내면 MPD가 파이프 command 프로세스 자체를 잃어 출력이 죽는다(→ MPD 크래시로 번짐).
# 루프로 즉시 재오픈해 MPD 쪽 stdin 연결은 유지한 채 리더 복귀를 기다린다.
while true; do
  cat >"$FIFO" || true
done
