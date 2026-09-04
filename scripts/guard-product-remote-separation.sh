#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRODUCT_DIR="${ROOT}/packages/remote"
TRIAL_DIR="${WHICK_TRIAL_SOURCE_DIR:-/data/whick-ai/2_control_center/site-web/public/trial-remote}"
errors=0

if [[ ! -d "$PRODUCT_DIR" ]]; then
  echo "[product-remote-guard] missing product SSOT: $PRODUCT_DIR" >&2
  exit 2
fi

# Static UI package must never contain backend sources.
while IFS= read -r -d '' bad; do
  echo "[product-remote-guard] backend source in product UI: $bad" >&2
  ((errors += 1))
done < <(find "$PRODUCT_DIR" -type f \( -name '*.py' -o -name '*.sql' -o -name '*.tar.gz' \) -print0)

# Markdown is excluded because it documents the forbidden boundary. Runtime and
# configuration files must not carry trial routes, switches, hosts, or sources.
# Relative /api/site/* on remote.whick.org is forbidden (SPA fallback). Short-link
# registration may use absolute https://whick.org/api/v1/site/... only.
contamination_re="(/trial-remote/|/api/site/trial|/api/site/radio|/api/site/weather|/api/site/streaming|fetch\\(['\\\"]/api/site|/pages/trial|whick-trial|music-4831|(^|[^[:alnum:]_])(isTrialEmbed|forceMock)([^[:alnum:]_]|$)|(^|[^[:alnum:]_])(trial|Trial|demo|Demo|mock|Mock)([-_[:upper:]]|[^[:alnum:]_]|$)|site-web/public/trial-remote|sync-trial-remote-to-product|WHICK_TRIAL_REMOTE|/data/whick-ai/2_control_center)"

while IFS= read -r -d '' file; do
  if matches="$(grep -I -nE -- "$contamination_re" "$file" || true)" && [[ -n "$matches" ]]; then
    echo "[product-remote-guard] trial contamination: $file" >&2
    printf '%s\n' "$matches" >&2
    ((errors += 1))
  fi
done < <(find "$PRODUCT_DIR" -type f ! -name '*.md' ! -path '*/i18n/*' -print0)

if [[ -d "$TRIAL_DIR" ]]; then
  declare -A trial_inodes=()
  while IFS= read -r -d '' trial_file; do
    inode="$(stat -Lc '%d:%i' "$trial_file")"
    trial_inodes["$inode"]=1
  done < <(find "$TRIAL_DIR" -type f -print0)

  while IFS= read -r -d '' product_file; do
    inode="$(stat -Lc '%d:%i' "$product_file")"
    if [[ -n "${trial_inodes[$inode]:-}" ]]; then
      echo "[product-remote-guard] hardlink to trial source: $product_file" >&2
      ((errors += 1))
    fi
  done < <(find "$PRODUCT_DIR" -type f -print0)

  trial_real="$(realpath -m "$TRIAL_DIR")"
  while IFS= read -r -d '' link; do
    resolved="$(realpath -m "$link")"
    case "$resolved" in
      "$trial_real"|"$trial_real"/*)
        echo "[product-remote-guard] symlink to trial source: $link -> $resolved" >&2
        ((errors += 1))
        ;;
    esac
  done < <(find "$PRODUCT_DIR" -type l -print0)
else
  echo "[product-remote-guard] trial tree unavailable; inode/link comparison skipped" >&2
fi

if (( errors > 0 )); then
  echo "[product-remote-guard] FAILED: $errors contaminated file/link(s)" >&2
  exit 1
fi

echo "[product-remote-guard] PASS: production remote is separated from trial"
