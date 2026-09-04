#!/usr/bin/env bash
# UAB payload tarball — IMG 빌드 전 번들 (live + 3_product runtime ref)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PRODUCT="$(cd "$ROOT/.." && pwd)"
STAMP="$(date +%Y%m%d)"
OUT="${WHICK_UAB_DIST:-$ROOT/../dist/uab}"
PAYLOAD="$OUT/whick-uab-payload-$STAMP"

mkdir -p "$PAYLOAD"

echo "==> UAB live"
rsync -a --delete \
  --exclude '__pycache__' \
  "$ROOT/live/" "$PAYLOAD/live/"

chmod +x "$PAYLOAD/live/boot.sh" "$PAYLOAD/live/bin/"*.sh "$PAYLOAD/live/bin/"*.py 2>/dev/null || true

echo "==> Windows USB Maker"
mkdir -p "$PAYLOAD/windows"
rsync -a "$ROOT/windows/" "$PAYLOAD/windows/"

echo "==> 3_product runtime (설치 대상)"
rsync -a \
  --exclude '.env' \
  --exclude 'library/incoming/*' \
  --exclude 'dist/' \
  --exclude '.git/' \
  "$PRODUCT/" "$PAYLOAD/whick-3_product/"

echo "==> phase scripts (from live/phases — do not stub if present)"
mkdir -p "$PAYLOAD/live/phases"
for p in 02_linux_install 03_docker 04_runtime; do
  src="$ROOT/live/phases/${p}.sh"
  if [[ -f "$src" ]]; then
    cp "$src" "$PAYLOAD/live/phases/${p}.sh"
    chmod +x "$PAYLOAD/live/phases/${p}.sh"
  else
    cat >"$PAYLOAD/live/phases/${p}.sh" <<'STUB'
#!/usr/bin/env bash
echo "[phase stub] $0 — missing live/phases source"
STUB
    chmod +x "$PAYLOAD/live/phases/${p}.sh"
  fi
done
rsync -a "$ROOT/live/bin/" "$PAYLOAD/live/bin/" --exclude '__pycache__'
rsync -a "$ROOT/live/lib/" "$PAYLOAD/live/lib/" 2>/dev/null || true
# boot-connect SSOT — payload에 live/lib로 동기화 (hw_collect)
cp -f "$ROOT/boot-connect/hw_identity.py" "$PAYLOAD/live/lib/hw_identity.py"
rsync -a "$ROOT/live/curtin/" "$PAYLOAD/live/curtin/" 2>/dev/null || true
chmod +x "$PAYLOAD/live/bin/"*.sh "$PAYLOAD/live/bin/"*.py "$PAYLOAD/live/phases/"*.sh 2>/dev/null || true

cp -f "$ROOT/README.md" "$PAYLOAD/"

ARCHIVE="$OUT/whick-uab-payload-$STAMP.tar.gz"
tar czf "$ARCHIVE" -C "$OUT" "$(basename "$PAYLOAD")"

WIN_ZIP="$OUT/whick-uab-windows-$STAMP.zip"
rm -f "$WIN_ZIP"
python3 - <<PY
import zipfile, os
from pathlib import Path
win = Path("$PAYLOAD/windows")
out = Path("$WIN_ZIP")
readme = Path("$ROOT/README.md")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in win.rglob("*"):
        if f.is_file():
            z.write(f, f.relative_to(win))
    if readme.is_file():
        z.write(readme, "README.md")
print("zip", out)
PY

echo ""
echo "OK  $ARCHIVE"
echo "OK  $WIN_ZIP  (VIP Room · Windows USB Maker)"
echo ""
echo "IMG 빌드 (추후): Ubuntu 26.04 live + overlay → whick-bootstrap.img"
