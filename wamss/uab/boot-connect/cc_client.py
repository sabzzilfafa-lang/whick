"""Whick CC /install/* — stdlib urllib (USB Live)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

CC_URL = os.environ.get("WHICK_CC_API_URL", "https://admin.whick.org/api/v1").rstrip("/")


def api_data(resp: dict) -> dict:
    if resp.get("ok") is True and isinstance(resp.get("data"), dict):
        return resp["data"]
    if resp.get("ok") is False:
        err = resp.get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise RuntimeError(msg or "api error")
    return resp


def cc_request(
    path: str,
    *,
    method: str = "GET",
    token: str = "",
    payload: dict | None = None,
    timeout: int = 30,
) -> dict:
    url = f"{CC_URL}{path}"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Whick-UAB-CustomerSetup/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError(raw or f"HTTP {e.code}") from e
        err = data.get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise RuntimeError(msg or f"HTTP {e.code}") from e


def report_install_link(
    token: str,
    *,
    lan_url: str = "",
    access_mode: str = "lan",
    hostname: str = "",
) -> dict:
    return api_data(
        cc_request(
            "/install/link",
            method="POST",
            token=token,
            payload={
                "type": "install_link",
                "payload": {
                    "lan_url": lan_url,
                    "access_mode": access_mode,
                    "hostname": hostname,
                },
            },
        )
    )


def report_hw_fingerprint(
    token: str,
    *,
    session_id: int,
    fingerprint: dict,
) -> dict:
    return api_data(
        cc_request(
            "/install/hw-report",
            method="POST",
            token=token,
            payload={
                "type": "hw_report",
                "payload": {
                    "session_id": session_id,
                    "fingerprint": fingerprint,
                },
            },
        )
    )


def keepalive_session(token: str, session_id: int) -> dict:
    return api_data(
        cc_request(
            f"/install/sessions/{session_id}/keepalive",
            method="POST",
            token=token,
            payload={"type": "install_keepalive", "payload": {}},
        )
    )


def cc_health_ok(timeout: int = 5) -> bool:
    """CC API health — LAN-only 설치(인터넷 ping 실패)에서도 session/me 폴링 허용."""
    try:
        api_data(cc_request("/system/health", timeout=timeout))
        return True
    except Exception:
        return False


def report_access_ready(
    token: str,
    session_id: int,
    *,
    access_mode: str,
    ap_ssid: str = "",
    device_code: str = "",
    captive_url: str = "",
    lan_url: str = "",
    ap_ok: bool = False,
) -> dict:
    return api_data(
        cc_request(
            f"/install/sessions/{session_id}/ap-ready",
            method="PATCH",
            token=token,
            payload={
                "type": "install_ap_ready",
                "payload": {
                    "access_mode": access_mode,
                    "ap_ok": ap_ok,
                    "ap_ssid": ap_ssid,
                    "device_code": device_code,
                    "captive_url": captive_url,
                    "lan_url": lan_url,
                },
            },
        )
    )


def report_ap_ready(
    token: str,
    session_id: int,
    *,
    ap_ssid: str,
    device_code: str = "",
    captive_url: str = "",
    lan_url: str = "",
) -> dict:
    mode = "ap" if ap_ssid and not lan_url else "lan"
    return report_access_ready(
        token,
        session_id,
        access_mode=mode,
        ap_ssid=ap_ssid,
        device_code=device_code,
        captive_url=captive_url,
        lan_url=lan_url,
        ap_ok=mode == "ap",
    )


def register_product(
    token: str,
    login: str,
    password: str,
    server_name: str = "Whick Music Server",
) -> dict:
    return api_data(
        cc_request(
            "/install/register-product",
            method="POST",
            token=token,
            payload={
                "type": "register_product",
                "payload": {
                    "login": login,
                    "password": password,
                    "server_name": server_name,
                },
            },
        )
    )


def submit_reinstall_consent(token: str, *, agreed: bool) -> dict:
    return api_data(
        cc_request(
            "/install/reinstall-consent",
            method="POST",
            token=token,
            payload={
                "type": "reinstall_consent",
                "payload": {"agreed": agreed},
            },
        )
    )


def fetch_install_session(token: str) -> dict:
    return api_data(cc_request("/install/session/me", token=token))


def auto_register_product(
    token: str,
    server_name: str = "Whick Music Server",
) -> dict:
    return api_data(
        cc_request(
            "/install/auto-register",
            method="POST",
            token=token,
            payload={
                "type": "auto_register",
                "payload": {"server_name": server_name},
            },
        )
    )


def ack_bootstrap_command(
    token: str,
    command_id: int,
    *,
    success: bool = True,
    message: str = "",
) -> dict:
    return api_data(
        cc_request(
            f"/install/bootstrap/commands/{command_id}/ack",
            method="POST",
            token=token,
            payload={
                "type": "bootstrap_command_ack",
                "payload": {"success": success, "message": message},
            },
        )
    )


def upload_bootstrap_logs(
    token: str,
    *,
    source: str,
    stage: str = "",
    status: str = "",
    exit_code: int | None = None,
    boot_id: str = "",
    message: str = "",
    logs: list[dict] | None = None,
    meta: dict | None = None,
) -> dict:
    return api_data(
        cc_request(
            "/install/bootstrap/logs",
            method="POST",
            token=token,
            payload={
                "type": "bootstrap_logs",
                "payload": {
                    "source": source,
                    "stage": stage,
                    "status": status,
                    "exit_code": exit_code,
                    "boot_id": boot_id,
                    "message": message,
                    "logs": logs or [],
                    "meta": meta or {},
                },
            },
            timeout=60,
        )
    )


def patch_session_progress(
    token: str,
    session_id: int,
    *,
    phase: str = "",
    progress_pct: int | None = None,
    phase_progress_pct: int | None = None,
    progress_msg: str = "",
) -> dict:
    payload: dict = {"type": "install_progress", "payload": {}}
    inner = payload["payload"]
    if phase:
        inner["phase"] = phase
    if progress_pct is not None:
        inner["progress_pct"] = progress_pct
    if phase_progress_pct is not None:
        inner["phase_progress_pct"] = phase_progress_pct
    if progress_msg:
        inner["progress_msg"] = progress_msg
    return api_data(
        cc_request(
            f"/install/sessions/{session_id}/progress",
            method="PATCH",
            token=token,
            payload=payload,
        )
    )


def fetch_remote_phase_bundle(token: str, dest_dir: str, *, timeout: int = 120) -> str:
    """CC orchestrator phase 5~7 bundle (tar.gz) — USB는 연동만, 설치 스크립트는 서버."""
    import tarfile
    import io
    from pathlib import Path

    dest = Path(dest_dir)
    marker = dest / ".bundle-ok"
    docker_phase = dest / "phases" / "03_docker.sh"
    cc_client = dest / "bin" / "cc_client.py"
    remote_version = ""
    try:
        remote_version = fetch_remote_phase_bundle_meta(token, timeout=min(timeout, 30))
    except Exception:
        remote_version = ""
    cached_version = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
    if (
        marker.is_file()
        and docker_phase.is_file()
        and cc_client.is_file()
        and remote_version
        and cached_version == remote_version
    ):
        return cached_version or "local"
    if marker.is_file() and remote_version and cached_version != remote_version:
        marker.unlink(missing_ok=True)

    url = f"{CC_URL}/install/bootstrap/phase-bundle"
    headers = {
        "Accept": "application/gzip",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Whick-UAB-CustomerSetup/1.0",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        version = r.headers.get("X-Whick-Phase-Bundle-Version", "")
        raw = r.read()
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    dest_root = dest.resolve()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        for member in tf.getmembers():
            target = (dest_root / member.name).resolve()
            if target != dest_root and not str(target).startswith(str(dest_root) + "/"):
                raise tarfile.TarError(f"unsafe bundle member: {member.name}")
        extract_kw = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tf.extractall(dest, **extract_kw)
    marker = dest / ".bundle-ok"
    marker.write_text(version or "ok", encoding="utf-8")
    return str(version or "ok")


def fetch_remote_phase_bundle_meta(token: str, *, timeout: int = 30) -> str:
    url = f"{CC_URL}/install/bootstrap/phase-bundle/meta"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Whick-UAB-CustomerSetup/1.0",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        return str(inner.get("version") or "").strip()
    except json.JSONDecodeError:
        return ""
