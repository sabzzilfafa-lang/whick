#!/bin/bash
set -e
cd /data/suno-helper
git fetch /tmp/suno_helper.bundle master:suno-desktop
git fetch origin
git checkout -B release origin/main
git rm -r -q suno-helper 2>/dev/null || true
git read-tree --prefix=suno-helper/ -u suno-desktop
git commit -q -m "suno-helper: account.html Korean mojibake fix (HTML entities + JS unicode escapes)"
git log --oneline -1
git push origin release:main
git checkout master 2>/dev/null || true
git branch -D suno-desktop || true
rm -f /tmp/suno_helper.bundle
echo PUSH_DONE
