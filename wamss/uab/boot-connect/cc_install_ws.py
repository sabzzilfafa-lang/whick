"""Minimal WebSocket client for /ws/install-device — stdlib only (USB Live)."""
from __future__ import annotations

import json
import os
import socket
import ssl
import struct
import threading
import time
from base64 import b64encode
from hashlib import sha1
from typing import Callable
from urllib.parse import urlparse

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("websocket closed")
        buf += chunk
    return buf


def _parse_ws_url(url: str) -> tuple[str, int, str, bool]:
    p = urlparse(url)
    secure = p.scheme == "wss"
    host = p.hostname or "127.0.0.1"
    port = p.port or (443 if secure else 80)
    path = p.path or "/"
    if p.query:
        path = f"{path}?{p.query}"
    return host, port, path, secure


def ws_connect(url: str, timeout: float = 12.0) -> socket.socket:
    host, port, path, secure = _parse_ws_url(url)
    raw = socket.create_connection((host, port), timeout=timeout)
    raw.settimeout(timeout)
    if secure:
        ctx = ssl.create_default_context()
        if os.environ.get("WHICK_CC_WS_INSECURE", "").strip() in ("1", "true", "yes"):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        sock = ctx.wrap_socket(raw, server_hostname=host)
    else:
        sock = raw

    key = b64encode(os.urandom(16)).decode("ascii")
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(req.encode("ascii"))
    resp = b""
    while b"\r\n\r\n" not in resp:
        resp += sock.recv(4096)
        if not resp:
            raise ConnectionError("websocket handshake empty")
    status_line = resp.split(b"\r\n", 1)[0]
    if b" 101 " not in status_line:
        raise ConnectionError(f"websocket handshake failed: {status_line.decode(errors='replace')[:120]}")
    expected = b64encode(sha1((key + WS_GUID).encode("ascii")).digest()).decode("ascii")
    if expected.encode() not in resp:
        raise ConnectionError("websocket Sec-WebSocket-Accept mismatch")
    return sock


def ws_send_text(sock: socket.socket, text: str) -> None:
    data = text.encode("utf-8")
    mask_key = os.urandom(4)
    frame = bytearray([0x81])
    length = len(data)
    if length < 126:
        frame.append(0x80 | length)
    elif length < 65536:
        frame.append(0x80 | 126)
        frame.extend(struct.pack("!H", length))
    else:
        frame.append(0x80 | 127)
        frame.extend(struct.pack("!Q", length))
    frame.extend(mask_key)
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(data))
    frame.extend(masked)
    sock.sendall(frame)


def ws_send_pong(sock: socket.socket, payload: bytes = b"") -> None:
    mask_key = os.urandom(4)
    frame = bytearray([0x8A])
    length = len(payload)
    if length < 126:
        frame.append(0x80 | length)
    elif length < 65536:
        frame.append(0x80 | 126)
        frame.extend(struct.pack("!H", length))
    else:
        frame.append(0x80 | 127)
        frame.extend(struct.pack("!Q", length))
    frame.extend(mask_key)
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    frame.extend(masked)
    sock.sendall(frame)


def ws_recv_text(sock: socket.socket) -> str | None:
    h1, h2 = struct.unpack("!BB", _recv_exact(sock, 2))
    opcode = h1 & 0x0F
    masked = (h2 & 0x80) != 0
    length = h2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(sock, 8))[0]
    mask = _recv_exact(sock, 4) if masked else b""
    payload = _recv_exact(sock, length)
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    if opcode == 0x8:
        return None
    if opcode == 0x9:
        ws_send_pong(sock, payload)
        return ws_recv_text(sock)
    if opcode not in (0x1, 0x2):
        return ws_recv_text(sock)
    return payload.decode("utf-8", errors="replace")


def install_device_ws_loop(
    url: str,
    on_message: Callable[[dict], None],
    *,
    stop: threading.Event | None = None,
    ping_interval: float = 25.0,
) -> None:
    """Connect and read until stop or disconnect (caller reconnects)."""
    sock = ws_connect(url)
    last_ping = time.time()
    try:
        while not (stop and stop.is_set()):
            if time.time() - last_ping >= ping_interval:
                try:
                    ws_send_text(sock, json.dumps({"type": "ping"}))
                except OSError:
                    break
                last_ping = time.time()
            try:
                raw = ws_recv_text(sock)
            except socket.timeout:
                continue
            except OSError:
                break
            if raw is None:
                break
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict):
                on_message(msg)
    finally:
        try:
            sock.close()
        except OSError:
            pass
