#!/usr/bin/env bash
# music-01 runtime 오프라인 번들 — pinned images · compose · install scripts
set -euo pipefail

PRODUCT="$(cd "$(dirname "$0")/.." && pwd)"
PRODUCT_MAP="$PRODUCT/scripts/apply-product-map.py"
python3 "$PRODUCT_MAP" apply --scope sources
LOCK="${WHICK_MUSIC01_LOCK:-/data/whick-ai/2_control_center/config/solutions/music-01.json}"
[[ -f "$LOCK" ]] || LOCK="$PRODUCT/install/runtime/components.lock.json"
OUT="${WHICK_MUSIC01_DIST:-$PRODUCT/dist/music-01}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

VER="$(python3 - "$LOCK" <<'PY'
import json, sys
print(json.load(open(sys.argv[1])).get("version", "v1.0.2"))
PY
)"
BUNDLE_FILE="music-01-runtime-${VER}.tar.zst"

python3 - <<'PY' "$LOCK" "$STAGE" "$PRODUCT"
import json, shutil, sys
from pathlib import Path

lock = json.load(open(sys.argv[1]))
stage = Path(sys.argv[2])
product = Path(sys.argv[3])
images = lock.get("components", {}).get("images") or {}

stage.mkdir(parents=True, exist_ok=True)
# install tree
rt_install = product / "install/runtime"
for sub in ("scripts",):
    src = rt_install / sub
    if src.is_dir():
        shutil.copytree(src, stage / sub, dirs_exist_ok=True)
# 배포 번들에는 이번 릴리스의 CC lock을 넣는다. 이전 product lock을 넣으면
# 업데이트 후 에이전트가 구버전으로 보고해 완료 처리가 되지 않는다.
shutil.copy2(Path(sys.argv[1]), stage / "components.lock.json")

# progress reporting tools (ssd ubuntu firstboot)
uab_live_bin = product / "uab/live/bin"
for f in ("cc_progress.py", "cc_client.py"):
    src = uab_live_bin / f
    if src.is_file():
        shutil.copy2(src, stage / "scripts" / f)

# retail compose — pinned tags (no :dev / :latest)
compose_src = product / "compose.yaml"
text = compose_src.read_text()
text = text.replace("whick/agent:dev", f"whick/agent:{images.get('whick/agent', 'v1.0.2')}")
text = text.replace("whick/audio:dev", f"whick/audio:{images.get('whick/audio', 'v1.0.2')}")
text = text.replace("whick/monitor:dev", f"whick/monitor:{images.get('whick/monitor', 'v1.0.2')}")
text = text.replace("whick/player:dev", f"whick/player:{images.get('whick/player', 'v1.0.2')}")
# lock SSOT = pgvector/pgvector (offline tar). postgres:16.8-alpine 으로 바꾸면
# docker load 는 pgvector만 있고 compose up player-db 가 No such image 로 실패한다.
if images.get("pgvector/pgvector"):
    text = text.replace(
        "postgres:16-alpine",
        f"pgvector/pgvector:{images['pgvector/pgvector']}",
    )
elif images.get("postgres"):
    text = text.replace("postgres:16-alpine", f"postgres:{images['postgres']}")
else:
    text = text.replace("postgres:16-alpine", "pgvector/pgvector:pg16")
text = text.replace("ollama/ollama:latest", f"ollama/ollama:{images.get('ollama/ollama', '0.6.2')}")
# retail: socket-proxy 이미지도 pinned (dev compose.yaml에 포함)
text = text.replace(
    "tecnativa/docker-socket-proxy:0.3.0",
    f"tecnativa/docker-socket-proxy:{images.get('tecnativa/docker-socket-proxy', '0.3.0')}",
)
(stage / "compose.yaml").write_text(text)
if (product / ".env.example").is_file():
    env_text = (product / ".env.example").read_text()
    # Retail mini-PC: LAN smartphone remote + Spotify OAuth redirect need 0.0.0.0 bind.
    env_text = env_text.replace(
        "WHICK_PLAYER_PORT_BIND=127.0.0.1:8080",
        "WHICK_PLAYER_PORT_BIND=0.0.0.0:8080",
    )
    env_text = env_text.replace(
        "WHICK_PLAYER_PORT80_BIND=127.0.0.1:80",
        "WHICK_PLAYER_PORT80_BIND=0.0.0.0:80",
    )
    (stage / ".env.example").write_text(env_text)
# seed demo music — 10 classical tracks for immediate playback testing
seed_music = product / "seed-music"
if seed_music.is_dir():
    shutil.copytree(seed_music, stage / "seed-music", dirs_exist_ok=True)
# Customer ALSA passthrough — camilla-pipe.sh needs /dev/snd + /proc/asound inside player.
# privileged: true required for ALSA detection (/proc/asound/cards).
# /lib/modules:ro required so entrypoint's ensure-aloop.sh `modprobe snd-aloop` can find the
# module (privileged alone grants CAP_SYS_MODULE but not the module files) — without this,
# modprobe silently fails every boot/reinstall and Camilla falls back to fifo (MPD hang risk).
# volumes MUST repeat whick-data (named bind mount) to prevent compose merge from dropping it.
(stage / "compose.override.yaml").write_text(
    """# Customer mini-PC — ALSA passthrough for MiniPC/DAC playback
services:
  player:
    privileged: true
    volumes:
      - /dev/snd:/dev/snd
      - /lib/modules:/lib/modules:ro
      - whick-data:/var/lib/whick
    group_add:
      - audio
    environment:
      WHICK_CAMILLA_ENABLED: "1"
      WHICK_CAMILLA_ALSA_DEVICE: ${WHICK_CAMILLA_ALSA_DEVICE:-auto}
"""
)
init_sql = product / "remote/api/init.sql"
if not init_sql.is_file():
    raise SystemExit(f"missing player schema: {init_sql}")
(stage / "remote/api").mkdir(parents=True, exist_ok=True)
shutil.copy2(init_sql, stage / "remote/api/init.sql")
(stage / "offline").mkdir(exist_ok=True)
(stage / "offline/images").mkdir(parents=True, exist_ok=True)
PY

mkdir -p "$OUT" "$STAGE/offline/images"

echo "==> docker save (pinned tags)"
python3 - <<'PY' "$LOCK" "$STAGE/offline/images"
import json, subprocess, sys
from pathlib import Path

lock = json.load(open(sys.argv[1]))
out = Path(sys.argv[2])
images = lock.get("components", {}).get("images") or {}
for repo, tag in images.items():
    ref = f"{repo}:{tag}"
    inspect = subprocess.run(["docker", "image", "inspect", ref], capture_output=True)
    if inspect.returncode != 0:
        print(f"pull {ref}")
        subprocess.check_call(["docker", "pull", ref])
    else:
        print(f"local {ref}")
    safe = ref.replace("/", "_").replace(":", "_")
    tar = out / f"{safe}.tar"
    subprocess.check_call(["docker", "save", "-o", str(tar), ref])
PY

mkdir -p "$OUT"
# 패킹 직전 stage lock 버전이 매니페스트와 같은지 강제 (rename-only 배포 차단)
python3 - <<'PY' "$LOCK" "$STAGE/components.lock.json" "$VER"
import json, sys
src = json.load(open(sys.argv[1]))
stage = json.load(open(sys.argv[2]))
want = sys.argv[3]
got_src = str(src.get("version") or "")
got_stage = str(stage.get("version") or "")
if got_src != want or got_stage != want:
    raise SystemExit(
        f"FATAL: components.lock version mismatch — want={want} "
        f"lock={got_src} stage={got_stage} (do not rename runtime tar only)"
    )
PY

ARCHIVE="$OUT/$BUNDLE_FILE"
rm -f "$ARCHIVE"
tar -cf - -C "$STAGE" . | zstd -T0 -19 -f -o "$ARCHIVE"
SHA="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
SIZE="$(stat -c%s "$ARCHIVE")"

# 아카이브 내부 lock 도 파일명 버전과 일치하는지 재확인
python3 - <<'PY' "$ARCHIVE" "$VER"
import json, subprocess, sys, tarfile
import io
archive, want = sys.argv[1], sys.argv[2]
# zstd -dc | tar extract member stream
p = subprocess.Popen(["zstd", "-dc", archive], stdout=subprocess.PIPE)
try:
    with tarfile.open(fileobj=p.stdout, mode="r|") as tf:
        found = None
        for m in tf:
            if m.name.endswith("components.lock.json"):
                f = tf.extractfile(m)
                found = json.load(f)
                break
finally:
    if p.stdout:
        p.stdout.close()
rc = p.wait()
if not found:
    raise SystemExit("FATAL: components.lock.json missing inside runtime archive")
if rc not in (0, -13, 141):
    raise SystemExit(f"zstd exit {rc}")
got = str(found.get("version") or "")
if got != want:
    raise SystemExit(f"FATAL: packed lock version {got} != {want}")
print("pack-ok lock_version", got)
PY

python3 - <<PY "$LOCK" "$ARCHIVE" "$SHA" "$SIZE" "$BUNDLE_FILE"
import json, sys
lock_path = sys.argv[1]
archive, sha, size, fname = sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
lock = json.load(open(lock_path))
lock.setdefault("components", {}).setdefault("runtime_bundle", {})
lock["components"]["runtime_bundle"].update({
    "file": fname,
    "sha256": sha,
    "size_bytes": size,
})
open(lock_path, "w").write(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
print("sha256", sha)
PY

python3 "$PRODUCT_MAP" apply --scope release

ls -lh "$ARCHIVE"
echo "OK  $ARCHIVE"
