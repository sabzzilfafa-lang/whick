#!/usr/bin/env bash
# Docker CE + compose plugin 오프라인 deb 번들 (Ubuntu 26.04 resolute · pinned)
set -euo pipefail

LOCK="${WHICK_MUSIC01_LOCK:-/data/whick-ai/2_control_center/config/solutions/music-01.json}"
OUT="${WHICK_MUSIC01_DIST:-/data/whick-ai_music_server/3_product/dist/music-01}"
IMAGE="${WHICK_DOCKER_DEB_IMAGE:-ubuntu:resolute}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

[[ -f "$LOCK" ]] || { echo "missing lock: $LOCK" >&2; exit 1; }
mkdir -p "$OUT" "$STAGE/debs"

eval "$(python3 - "$LOCK" <<'PY'
import json, sys
lock = json.load(open(sys.argv[1]))
dc = lock.get("components", {}).get("docker_ce", {}) or {}
dcp = lock.get("components", {}).get("docker_compose_plugin", {}) or {}
def q(s):
    return "'" + str(s).replace("'", "'\"'\"'") + "'"
print(f"export DOCKER_CE_VER={q(dc.get('version', ''))}")
print(f"export COMPOSE_VER={q(dcp.get('version', ''))}")
print(f"export BUNDLE_NAME={q(dc.get('deb_bundle', 'docker-ce-resolute-amd64.tar.zst'))}")
PY
)"

echo "==> download docker debs ($IMAGE)"
echo "    docker-ce=$DOCKER_CE_VER compose=$COMPOSE_VER"

docker run --rm \
  -e DEBIAN_FRONTEND=noninteractive \
  -e "DOCKER_CE_VER=$DOCKER_CE_VER" \
  -e "COMPOSE_VER=$COMPOSE_VER" \
  -v "$STAGE/debs:/debs" \
  "$IMAGE" \
  bash -ce '
    set -euo pipefail
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu resolute stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    cd /debs
    apt-get install -y --download-only -o Dir::Cache::archives=/debs \
      docker-ce="${DOCKER_CE_VER}" \
      docker-ce-cli="${DOCKER_CE_VER}" \
      docker-compose-plugin="${COMPOSE_VER}" \
      containerd.io \
      docker-buildx-plugin
    ls -1 *.deb | wc -l
  '

DEB_COUNT="$(find "$STAGE/debs" -maxdepth 1 -name '*.deb' | wc -l)"
[[ "$DEB_COUNT" -gt 0 ]] || { echo "no debs downloaded" >&2; exit 1; }
echo "    debs: $DEB_COUNT"

DEB_ONLY="$STAGE/debonly"
mkdir -p "$DEB_ONLY"
find "$STAGE/debs" -maxdepth 1 -name '*.deb' -exec cp -a {} "$DEB_ONLY/" \;

ARCHIVE="$OUT/$BUNDLE_NAME"
rm -f "$ARCHIVE"
tar -cf - -C "$DEB_ONLY" . | zstd -T0 -19 -q -f -o "$ARCHIVE"
SHA="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
SIZE="$(stat -c%s "$ARCHIVE")"

python3 <<PY "$LOCK" "$SHA" "$SIZE" "$BUNDLE_NAME"
import json, sys, pathlib
lock_path, sha, size, fname = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
lock = json.load(open(lock_path))
lock.setdefault("components", {}).setdefault("docker_ce", {})
lock["components"]["docker_ce"]["deb_bundle"] = fname
lock["components"]["docker_ce"]["deb_sha256"] = sha
lock["components"]["docker_ce"]["deb_size_bytes"] = size
open(lock_path, "w").write(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
prod = pathlib.Path("/data/whick-ai_music_server/3_product/install/runtime/components.lock.json")
if prod.parent.is_dir():
    prod.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
print("sha256", sha)
PY

ls -lh "$ARCHIVE"
PRODUCT_MAP="$(cd "$(dirname "$0")" && pwd)/apply-product-map.py"
python3 "$PRODUCT_MAP" apply --scope release
# release 스코프만 검증 — versions(sales-remote fallback 등)는 music-01 등록 후
# release-music-server.sh 가 별도로 apply/verify 한다. verify --scope all 은
# 아직 안 올린 fallback 때문에 번들 빌드 전에 실패한다.
python3 "$PRODUCT_MAP" verify --scope release
echo "OK  $ARCHIVE ($DEB_COUNT debs)"
