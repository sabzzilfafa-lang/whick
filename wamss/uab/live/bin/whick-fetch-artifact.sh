#!/usr/bin/env bash
# Whick 설치 아티팩트 — CC 우선(디폴트) · 인터넷/직접 URL은 비상
# 정책: cc_first_internet_emergency
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: whick-fetch-artifact.sh --name NAME --dest PATH [--sha256 HEX] [--url URL ...] [--prefer-cc|--prefer-url]

  디폴트: 중앙서버(CC) artifact → /downloads → --url(비상)
  --prefer-url: 예전 순서(URL 먼저) — 비상/디버그용
  WHICK_ARTIFACT_MIRROR — 추가 미러 베이스 URL
EOF
}

NAME=""
DEST=""
EXPECT_SHA=""
URLS=()
PREFER_CC=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="$2"; shift 2 ;;
    --dest) DEST="$2"; shift 2 ;;
    --sha256) EXPECT_SHA="$2"; shift 2 ;;
    --url) URLS+=("$2"); shift 2 ;;
    --prefer-cc) PREFER_CC=1; shift ;;
    --prefer-url) PREFER_CC=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown: $1" >&2; exit 1 ;;
  esac
done

[[ -n "$NAME" && -n "$DEST" ]] || { usage >&2; exit 1; }

for p in "${WHICK_BOOTSTRAP_SESSION:-}" /tmp/whick-bootstrap-session.json /var/lib/whick/bootstrap-session.json; do
  if [[ -n "$p" && -f "$p" ]]; then
    WHICK_BOOTSTRAP_SESSION="$p"
    break
  fi
done
SESSION="${WHICK_BOOTSTRAP_SESSION:-/var/lib/whick/bootstrap-session.json}"
CC="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
MIRROR="${WHICK_ARTIFACT_MIRROR:-}"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

fetch_url() {
  local url="$1" out="$2"
  echo "[fetch] $url"
  rm -f "$out"
  if [[ -f "$SESSION" ]] && command -v python3 >/dev/null 2>&1; then
    if python3 - "$url" "$out" "$SESSION" <<'PY'
import json, os, sys, urllib.error, urllib.request
url, dest, sess_path = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.load(open(sess_path))
token = data.get("bootstrap_token") or data.get("token") or ""
req = urllib.request.Request(url, headers={
    "Authorization": f"Bearer {token}",
    "User-Agent": "Whick-Install/1.0",
})
try:
    with urllib.request.urlopen(req, timeout=600) as r:
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
except Exception as e:
    try:
        os.remove(dest)
    except OSError:
        pass
    print(f"[fetch] python error: {e}", file=sys.stderr)
    raise SystemExit(1)
if not os.path.isfile(dest) or os.path.getsize(dest) <= 0:
    print("[fetch] empty download", file=sys.stderr)
    raise SystemExit(1)
PY
    then
      [[ -f "$out" && -s "$out" ]] || return 1
      return 0
    fi
    return 1
  fi
  curl -fsSL --retry 2 --connect-timeout 30 -o "$out" "$url" || return 1
  [[ -f "$out" && -s "$out" ]] || return 1
}

cc_default="${CC%/}/install/bootstrap/artifact/$NAME"
downloads_url="https://whick.org/downloads/$NAME"
cc_list=("$cc_default" "$downloads_url")
[[ -n "${WHICK_ARTIFACT_FALLBACK_URL:-}" ]] && cc_list+=("${WHICK_ARTIFACT_FALLBACK_URL%/}/$NAME")
[[ -n "$MIRROR" ]] && cc_list+=("${MIRROR%/}/$NAME")

url_list=()
for u in "${URLS[@]}"; do
  [[ -n "$u" ]] || continue
  # downloads/CC URL이 --url로 중복 들어오면 cc_list와 합치지 않음(순서만)
  url_list+=("$u")
done

try_list=()
if [[ "$PREFER_CC" -eq 1 ]]; then
  for u in "${cc_list[@]}"; do try_list+=("$u"); done
  for u in "${url_list[@]}"; do
    skip=0
    for c in "${cc_list[@]}"; do [[ "$u" == "$c" ]] && skip=1 && break; done
    [[ "$skip" -eq 1 ]] || try_list+=("$u")
  done
else
  for u in "${url_list[@]}"; do try_list+=("$u"); done
  for u in "${cc_list[@]}"; do try_list+=("$u"); done
fi

tmp="$tmpdir/$NAME"
ok=0
for url in "${try_list[@]}"; do
  [[ -n "$url" ]] || continue
  if fetch_url "$url" "$tmp" 2>/dev/null; then
    ok=1
    echo "[fetch] source_ok=$url"
    break
  fi
  echo "[fetch] WARN failed: $url" >&2
done

if [[ "$ok" -eq 0 ]]; then
  echo "[fetch] ERROR: all sources failed for $NAME" >&2
  exit 1
fi

if [[ -n "$EXPECT_SHA" ]]; then
  got="$(sha256sum "$tmp" | awk '{print $1}')"
  if [[ "$got" != "$EXPECT_SHA" ]]; then
    echo "[fetch] sha256 mismatch for $NAME (got $got)" >&2
    exit 1
  fi
fi

mkdir -p "$(dirname "$DEST")"
mv -f "$tmp" "$DEST"
echo "[fetch] OK $DEST"
