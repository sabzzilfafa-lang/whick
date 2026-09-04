#!/usr/bin/env bash
# dist/setup.deb 생성 — VIP Room 첨부 (Ubuntu setup.msi 와 같은 역할)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="/data/whick-ai_music_server"
OUT_DIR="${WHICK_3PRODUCT_DIST:-$ROOT/dist}"
SCRIPTS_DIR="$ROOT/scripts"
INSTALL_SH="$SCRIPTS_DIR/whick-customer-install.sh"
LAUNCH_SH="$ROOT/debian/launch-install.sh"
DESKTOP="$ROOT/debian/whick-setup.desktop"
POSTINST_SRC="$ROOT/debian/DEBIAN-postinst.sh"
SETUP_DEB="$OUT_DIR/setup.deb"
FALLBACK_DIR="$REPO/5_site/content/customer"
FALLBACK_SH="$FALLBACK_DIR/setup.sh"
STAMP="$(date +%Y%m%d)"
DEB_VER="${STAMP}.2"
WORK="$(mktemp -d)"

cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

mkdir -p "$OUT_DIR" "$FALLBACK_DIR"
for f in "$INSTALL_SH" "$LAUNCH_SH" "$DESKTOP" "$POSTINST_SRC" \
  "$SCRIPTS_DIR/whick-one-click-install.sh" \
  "$SCRIPTS_DIR/laptop-first-boot.sh" \
  "$SCRIPTS_DIR/laptop-power-always-on.sh" \
  "$SCRIPTS_DIR/whick-cc-url.sh"; do
  [[ -f "$f" ]] || { echo "missing $f" >&2; exit 1; }
done

cp "$INSTALL_SH" "$FALLBACK_SH"
chmod 644 "$FALLBACK_SH"

PKG="$WORK/whick-setup_${DEB_VER}_all"
LIB="$PKG/usr/lib/whick"
mkdir -p "$PKG/DEBIAN" "$LIB" "$PKG/usr/share/applications" "$PKG/usr/bin"

for s in customer-install launch-install whick-one-click-install laptop-first-boot laptop-power-always-on whick-cc-url; do
  src="$INSTALL_SH"
  case "$s" in
    customer-install) src="$INSTALL_SH" ;;
    launch-install) src="$LAUNCH_SH" ;;
    whick-one-click-install) src="$SCRIPTS_DIR/whick-one-click-install.sh" ;;
    laptop-first-boot) src="$SCRIPTS_DIR/laptop-first-boot.sh" ;;
    laptop-power-always-on) src="$SCRIPTS_DIR/laptop-power-always-on.sh" ;;
    whick-cc-url) src="$SCRIPTS_DIR/whick-cc-url.sh" ;;
  esac
  cp "$src" "$LIB/$s.sh"
  chmod 755 "$LIB/$s.sh"
done
# 호환 경로
ln -sf customer-install.sh "$LIB/customer-install"
cp "$DESKTOP" "$PKG/usr/share/applications/whick-setup.desktop"
ln -sf ../lib/whick/launch-install.sh "$PKG/usr/bin/whick-setup"

cat >"$PKG/DEBIAN/control" <<EOF
Package: whick-setup
Version: ${DEB_VER}
Section: misc
Priority: optional
Architecture: all
Maintainer: Whick <admin@whick.org>
Description: Whick Music Server customer setup (VIP Room)
 Install launcher. Scripts in /usr/lib/whick/.
EOF

cp "$POSTINST_SRC" "$PKG/DEBIAN/postinst"
chmod 755 "$PKG/DEBIAN/postinst"

dpkg-deb --root-owner-group --build "$PKG" "$SETUP_DEB"
chmod 644 "$SETUP_DEB"

echo "OK  $SETUP_DEB ($(du -h "$SETUP_DEB" | cut -f1))"
echo "OK  $FALLBACK_SH (https://whick.org/whick-content/customer/setup.sh)"
