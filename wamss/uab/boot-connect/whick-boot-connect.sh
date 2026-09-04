#!/bin/sh
# USB 부팅 Live — CC 연결: 1) link(서버) 2) hw-report(raw DMI, hash는 서버)
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"
export WHICK_BOOT_CONNECT_ROOT="$ROOT"
# live-debug.env 가 이미 공개 HTTPS CC 를 넣었다면, whick-env.sh 의 lab localhost 핀이
# 덮어쓰지 못하게 보존한다 (2026-08-03 server_unreachable 사고).
_PRESERVE_CC_API_URL="${WHICK_CC_API_URL:-}"
_PRESERVE_CANONICAL_CC_API_URL="${WHICK_CANONICAL_CC_API_URL:-}"
if [ -f "$ROOT/whick-env.sh" ]; then
  # shellcheck source=/dev/null
  . "$ROOT/whick-env.sh"
fi
case "${_PRESERVE_CC_API_URL}" in
  https://*)
    WHICK_CC_API_URL="${_PRESERVE_CC_API_URL}"
    WHICK_CANONICAL_CC_API_URL="${_PRESERVE_CANONICAL_CC_API_URL:-$_PRESERVE_CC_API_URL}"
    export WHICK_CC_API_URL WHICK_CANONICAL_CC_API_URL
    ;;
esac

WHICK_CANONICAL_CC_API_URL="${WHICK_CANONICAL_CC_API_URL:-https://admin.whick.org/api/v1}"
CC_URL="${WHICK_CC_API_URL:-$WHICK_CANONICAL_CC_API_URL}"
if [ "${WHICK_PROD_INSTALL:-0}" = "1" ] && [ "${WHICK_ALLOW_NON_TUNNEL_CC:-0}" != "1" ]; then
  CC_URL="$WHICK_CANONICAL_CC_API_URL"
fi
# 현장 설치 USB 는 localhost CC 금지
case "$CC_URL" in
  *127.0.0.1*|*localhost*)
    if [ "${WHICK_ALLOW_LOCALHOST_CC:-0}" != "1" ]; then
      echo "ERROR: localhost CC URL not allowed on field USB: $CC_URL" >&2
      echo "  live-debug.env / whick-env.sh 를 공개 터널 CC URL로 다시 빌드하세요." >&2
      exit 1
    fi
    ;;
esac
HEALTH_URL="${WHICK_CC_HEALTH_URL:-${CC_URL%/}/system/health}"
RESULT="${WHICK_CONNECT_RESULT:-/tmp/whick-connect-result.json}"
LOG="${WHICK_CONNECT_LOG:-/tmp/whick-connect.log}"
BOOTSTRAP_SESSION="${WHICK_BOOTSTRAP_SESSION:-/tmp/whick-bootstrap-session.json}"

exec >>"$LOG" 2>&1
echo "=== $(date -Iseconds 2>/dev/null || date) Whick boot connect ==="
: >"$RESULT"

upload_boot_connect_logs() {
  rc="$1"
  set +e
  [ -f "$BOOTSTRAP_SESSION" ] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  python3 - <<'PY' "$BOOTSTRAP_SESSION" "$CC_URL" "$rc" "$LOG" "$RESULT" || true
import json
import os
import sys
import urllib.request

state_path, cc_url, rc_s, log_path, result_path = sys.argv[1:]
try:
    state = json.load(open(state_path))
except Exception:
    raise SystemExit(0)
token = state.get("bootstrap_token") or state.get("token")
if not token:
    raise SystemExit(0)

def read_tail(path, limit=1000000):
    if not path or not os.path.isfile(path):
        return ""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - limit))
        return f.read().decode("utf-8", errors="replace")

logs = []
for name, path in (("whick-connect.log", log_path), ("WHICK-CONNECT-RESULT.json", result_path)):
    content = read_tail(path)
    if content:
        logs.append({"name": name, "path": path, "content": content})
if not logs:
    raise SystemExit(0)
try:
    rc = int(rc_s)
except Exception:
    rc = 1
status = "complete" if rc == 0 else "failed"
payload = {
    "type": "bootstrap_logs",
    "payload": {
        "source": "usb-boot-connect",
        "stage": "boot-connect",
        "status": status,
        "exit_code": rc,
        "message": "USB boot-connect complete" if rc == 0 else "USB boot-connect failed; see uploaded logs",
        "logs": logs,
        "meta": {
            "device_code": state.get("device_code", ""),
            "session_id": state.get("session_id"),
        },
    },
}
req = urllib.request.Request(
    cc_url.rstrip("/") + "/install/bootstrap/logs",
    data=json.dumps(payload, ensure_ascii=False).encode(),
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Whick-USB-BootConnect/1.0",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        print("[boot-connect] log upload OK", resp.status)
except Exception as e:
    print("[boot-connect] log upload failed", e)
PY
}

finish_boot_connect() {
  rc="$?"
  upload_boot_connect_logs "$rc" || true
  exit "$rc"
}
trap finish_boot_connect EXIT

wait_net() {
  i=0
  while [ "$i" -lt 45 ]; do
    ping -c1 -W2 8.8.8.8 >/dev/null 2>&1 && return 0
    i=$((i + 1))
    sleep 2
  done
  return 1
}

save_usb() {
  if [ -n "${WHICK_USB_ROOT:-}" ] && [ -d "$WHICK_USB_ROOT" ]; then
    cp -f "$RESULT" "$WHICK_USB_ROOT/WHICK-CONNECT-RESULT.json" 2>/dev/null && \
      echo "saved $WHICK_USB_ROOT/WHICK-CONNECT-RESULT.json" && return 0
  fi
  for base in /mnt/whick-ventoy /media/* /media/*/* /run/media/* /run/media/*/*; do
    [ -d "$base" ] || continue
    if [ -d "$base/whick-boot-connect" ] || [ -f "$base/whick.apkovl.tar.gz" ] || [ -f "$base/alpine.apkovl.tar.gz" ]; then
      cp -f "$RESULT" "$base/WHICK-CONNECT-RESULT.json" 2>/dev/null && echo "saved $base/WHICK-CONNECT-RESULT.json"
      return 0
    fi
  done
  return 1
}

if ! wait_net; then
  echo "NG network"
  echo '{"ok":false,"error":"network","error_code":"network"}' >"$RESULT"
  save_usb || true
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "NG python3 required"
  echo '{"ok":false,"error":"python3 missing"}' >"$RESULT"
  save_usb || true
  exit 1
fi

export CC_URL HEALTH_URL RESULT LOG WHICK_LAN_URL="${WHICK_LAN_URL:-}" WHICK_BOOT_CONNECT_ROOT
python3 <<'PY'
import json, os, subprocess, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.environ.get("WHICK_BOOT_CONNECT_ROOT", "."))

SKIP_HW = os.environ.get("WHICK_SKIP_HW_ID", "0").strip().lower() not in ("0", "false", "no")
if not SKIP_HW:
    from hw_identity import collect_dmi_raw_for_server


class ApiHttpError(RuntimeError):
    def __init__(self, http_code, message, api_code=None):
        super().__init__(message)
        self.http_code = http_code
        self.api_code = api_code or ""

cc = os.environ["CC_URL"].rstrip("/")
health = os.environ["HEALTH_URL"]
result_path = os.environ["RESULT"]
lan_url = os.environ.get("WHICK_LAN_URL", "").strip()
out = {
    "ok": False,
    "health_ok": False,
    "session_ok": False,
    "link_ok": False,
    "hw_report_ok": False,
    "device_code": "",
    "session_id": None,
    "hw_id_hash": "",
    "cc_url": cc,
    "at": datetime.now(timezone.utc).astimezone().isoformat(),
}

bootstrap_path = os.environ.get("WHICK_BOOTSTRAP_SESSION", "/tmp/whick-bootstrap-session.json")
_boot_root = os.environ.get("WHICK_BOOT_CONNECT_ROOT") or "."


def seed_bootstrap_session_from_media():
    """맞춤 USB — ISO/미디어의 whick-bootstrap-session.json 을 /tmp 로 복사 후 재사용.
    /tmp 만 보면 새 DIY 세션이 만들어져 MUSIC-JJPS 가 QUQT 로 바뀌는 사고 방지."""
    if os.path.isfile(bootstrap_path):
        try:
            data = json.load(open(bootstrap_path, encoding="utf-8"))
            if str(data.get("bootstrap_token") or "").strip():
                return
        except (OSError, json.JSONDecodeError):
            pass
    candidates = [
        os.path.join(_boot_root, "whick-bootstrap-session.json"),
        "/opt/whick/boot-connect/whick-bootstrap-session.json",
        "/opt/whick-boot-connect/whick-bootstrap-session.json",
        "/etc/whick/whick-bootstrap-session.json",
        "/mnt/whick-media/whick-os/opt/whick/boot-connect/whick-bootstrap-session.json",
        "/cdrom/whick-os/opt/whick/boot-connect/whick-bootstrap-session.json",
        "/mnt/whick-media/casper/whick-os/opt/whick/boot-connect/whick-bootstrap-session.json",
        "/cdrom/casper/whick-os/opt/whick/boot-connect/whick-bootstrap-session.json",
    ]
    for src in candidates:
        if not src or not os.path.isfile(src):
            continue
        try:
            data = json.load(open(src, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not str(data.get("bootstrap_token") or "").strip():
            continue
        try:
            os.makedirs(os.path.dirname(bootstrap_path) or "/tmp", exist_ok=True)
            with open(bootstrap_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.chmod(bootstrap_path, 0o600)
            print("BOOTSTRAP SEEDED", src, "->", bootstrap_path, data.get("device_code", ""))
            return
        except OSError as e:
            print("BOOTSTRAP SEED FAIL", src, e)
            return


seed_bootstrap_session_from_media()

def ensure_dns():
    """USB Live — DHCP DNS 누락 시 admin.whick.org 해석 실패 방지."""
    try:
        if "nameserver" in Path("/etc/resolv.conf").read_text():
            return
    except OSError:
        pass
    try:
        Path("/etc/resolv.conf").write_text("nameserver 8.8.8.8\nnameserver 1.1.1.1\n")
    except OSError:
        pass


def install_secret_headers():
    secret = (
        os.environ.get("WHICK_INSTALL_BOOTSTRAP_SECRET")
        or os.environ.get("CC_INSTALL_BOOTSTRAP_SECRET")
        or ""
    ).strip()
    if not secret:
        return {}
    return {"X-Whick-Install-Secret": secret}


def curl_json_via_curl(url, method="GET", data=None, headers=None):
    """urllib 실패(SSL/DNS/IPv6) 시 mini curl -4 폴백."""
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Whick-UAB-BootConnect/1.0",
    }
    h.update(install_secret_headers())
    if headers:
        h.update(headers)
    cmd = ["curl", "-4", "-fsS", "-m", "25", "-X", method]
    ca = os.environ.get("SSL_CERT_FILE", "")
    if ca and os.path.isfile(ca):
        cmd += ["--cacert", ca]
    for k, v in h.items():
        cmd += ["-H", f"{k}: {v}"]
    if data is not None:
        cmd += ["-d", json.dumps(data)]
    cmd.append(url)
    try:
        raw = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return json.loads(raw)
    except subprocess.CalledProcessError as e:
        out_raw = (e.output or str(e))[:240]
        raise RuntimeError(out_raw) from e


def write_result():
    with open(result_path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

def curl_json(url, method="GET", data=None, headers=None):
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Whick-UAB-BootConnect/1.0",
    }
    h.update(install_secret_headers())
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise ApiHttpError(e.code, raw[:240] or f"HTTP {e.code}") from e
        err = payload.get("error") or {}
        raise ApiHttpError(
            e.code,
            err.get("message") or raw[:240] or f"HTTP {e.code}",
            err.get("code") or "",
        ) from e
    except Exception as urllib_err:
        try:
            return curl_json_via_curl(url, method=method, data=data, headers=headers)
        except Exception as curl_err:
            raise RuntimeError(f"{urllib_err}; curl: {curl_err}") from curl_err

def api_data(resp):
    if isinstance(resp, dict) and resp.get("ok") is True and isinstance(resp.get("data"), dict):
        return resp["data"]
    if isinstance(resp, dict) and resp.get("ok") is False:
        err = resp.get("error") or {}
        raise RuntimeError(err.get("message") or "api error")
    return resp

def ram_gb():
    try:
        from hw_identity import normalize_ram_gb_from_memtotal_kb
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return normalize_ram_gb_from_memtotal_kb(int(line.split()[1]))
    except OSError:
        pass
    return 0


def collect_nics():
    import re

    nics = []
    try:
        out = subprocess.check_output(["lspci", "-nn"], stderr=subprocess.DEVNULL, text=True)
    except (OSError, subprocess.CalledProcessError):
        return nics
    for line in out.splitlines():
        low = line.lower()
        if not any(k in low for k in ("ethernet", "network controller", "wireless", "wifi", "802.11")):
            continue
        m = re.search(r"\[([0-9a-f]{4}):([0-9a-f]{4})\]", line, re.I)
        if not m:
            continue
        if any(k in low for k in ("wireless", "wifi", "802.11")):
            kind = "wifi"
        elif "ethernet controller" in low or "ethernet connection" in low:
            kind = "eth"
        elif "network controller" in low and "ethernet" not in low:
            kind = "wifi"
        else:
            kind = "eth"
        name = line.split(": ", 2)[-1].strip()
        nics.append(
            {
                "kind": kind,
                "vendor_id": m.group(1).lower(),
                "device_id": m.group(2).lower(),
                "pci_id": f"{m.group(1)}:{m.group(2)}".lower(),
                "name": name,
            }
        )
    return nics

def cc_api_url_for_device():
    if lan_url.startswith("http"):
        from urllib.parse import urlparse

        u = urlparse(lan_url)
        host = u.hostname or ""
        scheme = u.scheme or "http"
        if host:
            return f"{scheme}://{host}/api/v1"
    return cc


def save_bootstrap(token):
    try:
        with open(bootstrap_path, "w") as f:
            json.dump(
                {
                    "session_id": out["session_id"],
                    "device_code": out["device_code"],
                    "bootstrap_token": token,
                    "hw_id_hash": out.get("hw_id_hash") or "",
                    # SSD firstboot must reuse the CC base URL that passed health/link here,
                    # not lan_url (mini-PC captive UI host — wrong for /api/v1).
                    "cc_api_url": cc,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        os.chmod(bootstrap_path, 0o600)
        return True
    except OSError as e:
        out["bootstrap_save_error"] = str(e)
        return False


def require_bootstrap_save(token):
    if save_bootstrap(token):
        return
    out["ok"] = False
    out["link_ok"] = False
    out["error"] = out.get("bootstrap_save_error") or "bootstrap save failed"
    out["error_code"] = "bootstrap_save"
    write_result()
    sys.exit(1)

health_err = None
ensure_dns()
for attempt in range(4):
    try:
        health_resp = curl_json(health)
        out["health_ok"] = bool(health_resp.get("ok"))
        if out["health_ok"]:
            health_err = None
            break
        health_err = "health not ok"
    except Exception as e:
        health_err = f"health: {e}"
    if attempt < 3:
        time.sleep(3)

if health_err:
    out["error"] = health_err
    out["error_code"] = "server_unreachable"
    write_result()
    sys.exit(1)

def try_reuse_bootstrap():
    if not os.path.isfile(bootstrap_path):
        return None
    try:
        data = json.load(open(bootstrap_path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    token = str(data.get("bootstrap_token") or "").strip()
    if not token:
        return None
    try:
        sess = api_data(
            curl_json(
                f"{cc}/install/session/me",
                headers={"Authorization": f"Bearer {token}"},
            )
        )
    except ApiHttpError as e:
        if e.http_code in (401, 403):
            return None
        raise
    except Exception:
        return None
    phase = str(sess.get("phase") or "")
    if phase == "complete":
        return None
    return {
        "token": token,
        "session_id": sess.get("session_id") or sess.get("id") or data.get("session_id"),
        "device_code": sess.get("device_code") or data.get("device_code", ""),
        "hw_id_hash": sess.get("hw_id_hash") or data.get("hw_id_hash") or "",
        "phase": phase,
        "sess": sess,
    }

reused = try_reuse_bootstrap()
token = ""
if reused:
    token = reused["token"]
    out["session_ok"] = True
    out["session_id"] = reused["session_id"]
    out["device_code"] = reused["device_code"]
    out["bootstrap_reused"] = True
    if reused.get("hw_id_hash"):
        out["hw_id_hash"] = reused["hw_id_hash"]
    phase = reused.get("phase") or ""
    if phase in (
        "register_done",
        "install_linux",
        "install_docker",
        "install_runtime",
        "register_pending",
        "hw_analyzed",
        "await_phone",
    ):
        out["ok"] = True
        out["link_ok"] = True
        out["hw_report_ok"] = bool(reused.get("hw_id_hash"))
        require_bootstrap_save(token)
        write_result()
        print("REUSE OK", out["device_code"], phase)
        sys.exit(0)
else:
    try:
        sess = api_data(
            curl_json(
                f"{cc}/install/sessions",
                method="POST",
                data={
                    "type": "install_session_create",
                    "payload": {"install_path": "diy", "hostname_hint": os.uname().nodename},
                },
            )
        )
        out["session_ok"] = True
        out["device_code"] = sess.get("device_code", "")
        out["session_id"] = sess.get("session_id")
        token = sess.get("bootstrap_token", "")
    except ApiHttpError as e:
        out["error"] = f"session: {e}"
        out["error_code"] = (
            "install_complete" if e.api_code == "INSTALL_ALREADY_COMPLETE" else "server_register"
        )
        out["api_error_code"] = e.api_code or None
        write_result()
        sys.exit(1)
    except Exception as e:
        out["error"] = f"session: {e}"
        out["error_code"] = "server_register"
        write_result()
        sys.exit(1)

if not lan_url.startswith("http"):
    lan_url = os.environ.get("WHICK_LAN_URL", "").strip()

# Phase A — link (HW 없이 서버 연결)
link_err = None
link_data = None
for attempt in range(3):
    try:
        link_payload = {
            "type": "install_link",
            "payload": {
                "hostname": os.uname().nodename,
                "access_mode": "lan" if lan_url.startswith("http") else "",
            },
        }
        if lan_url.startswith("http"):
            link_payload["payload"]["lan_url"] = lan_url
        link_data = api_data(
            curl_json(
                f"{cc}/install/link",
                method="POST",
                headers={"Authorization": f"Bearer {token}"},
                data=link_payload,
            )
        )
        out["link_ok"] = True
        if link_data.get("hw_id_hash"):
            out["hw_id_hash"] = link_data["hw_id_hash"]
            out["hw_report_ok"] = True
            out["hw_skip"] = bool(link_data.get("hw_skip"))
        if link_data.get("phone_invite"):
            out["phone_invite"] = link_data["phone_invite"]
        link_err = None
        break
    except ApiHttpError as e:
        link_err = e
        if e.http_code in (401, 403, 409) or attempt >= 2:
            break
    except Exception as e:
        link_err = e
    if attempt < 2:
        time.sleep(3)

if link_err:
    out["error"] = f"link: {link_err}"
    out["error_code"] = "server_register"
    if isinstance(link_err, ApiHttpError):
        out["api_error_code"] = link_err.api_code or None
    write_result()
    sys.exit(1)

require_bootstrap_save(token)
out["ok"] = True
write_result()
print("LINK OK", out["device_code"])

# 서버 skip + hash 확보 시 Phase B 생략 (클라 WHICK_SKIP_HW_ID 와 무관하게 서버 응답 기준)
server_hw_skip = bool((link_data or {}).get("hw_skip"))
if out.get("hw_report_ok") or (server_hw_skip and out.get("hw_id_hash")):
    require_bootstrap_save(token)
    write_result()
    print("OK (hw skip)" if server_hw_skip else "OK", out["device_code"])
    sys.exit(0)

# Phase B — raw DMI hw-report (SKIP_HW 또는 서버 skip 시 생략)
if SKIP_HW:
    print("Phase B skipped — WHICK_SKIP_HW_ID")
else:
    try:
        mb_raw, identity_source = collect_dmi_raw_for_server(retries=4, retry_delay_sec=1.5)
        fp = {
            "hostname": os.uname().nodename,
            "source": "usb-boot-connect",
            "kernel": os.uname().release,
            "ram_gb": ram_gb(),
            "nics": collect_nics(),
            "motherboard": mb_raw,
            "identity_source": identity_source,
        }
        try:
            from hw_identity import collect_hw_runtime_specs

            fp.update(collect_hw_runtime_specs())
        except Exception:
            pass
        if lan_url.startswith("http"):
            fp["lan_url"] = lan_url
            fp["access_mode"] = "lan"

        hr_err = None
        hr = None
        for attempt in range(4):
            try:
                hr = api_data(
                    curl_json(
                        f"{cc}/install/hw-report",
                        method="POST",
                        headers={"Authorization": f"Bearer {token}"},
                        data={
                            "type": "hw_report",
                            "payload": {
                                "session_id": out["session_id"],
                                "fingerprint": fp,
                            },
                        },
                    )
                )
                hr_err = None
                break
            except ApiHttpError as e:
                hr_err = e
                if e.http_code in (401, 403, 409):
                    break
            except Exception as e:
                hr_err = e
            if attempt < 3:
                time.sleep(4)

        if hr and not hr_err:
            out["hw_report_ok"] = True
            out["hw_id_hash"] = hr.get("hw_id_hash") or hr.get("hw_id_hash_server") or ""
            out["phone_invite"] = hr.get("phone_invite") or {}
            require_bootstrap_save(token)
        elif hr_err:
            out["hw_report_error"] = str(hr_err)
            out["hw_report_error_code"] = hr_err.api_code if isinstance(hr_err, ApiHttpError) else "hw_identity"
            print("HW report failed (link ok):", hr_err)
    except Exception as e:
        out["hw_report_error"] = str(e)
        out["hw_report_error_code"] = "hw_identity"
        print("HW phase exception (link ok):", e)

write_result()
print("OK", out["device_code"])
bootstrap_ok = os.path.isfile(bootstrap_path) and bool(token)
if not bootstrap_ok:
    out["ok"] = False
    out["link_ok"] = False
    out["error"] = out.get("error") or "bootstrap session missing"
    out["error_code"] = out.get("error_code") or "bootstrap_save"
    write_result()
sys.exit(0 if out.get("link_ok") and bootstrap_ok else 1)
PY

rc=$?
if [ ! -s "$RESULT" ] || ! grep -q '"ok"' "$RESULT" 2>/dev/null; then
  last=$(tail -1 "$LOG" 2>/dev/null | tr -d '\n\r' | head -c 180)
  [ -z "$last" ] && last="boot-connect failed (exit $rc)"
  export RESULT LAST
  python3 - <<'PY2'
import json, os
open(os.environ["RESULT"], "w").write(json.dumps({
    "ok": False,
    "error": os.environ.get("LAST") or "boot-connect failed",
    "error_code": "server_unreachable",
}, ensure_ascii=False))
PY2
fi
save_usb || true

if [ "$rc" -eq 0 ]; then
  exit 0
fi

exit 1
