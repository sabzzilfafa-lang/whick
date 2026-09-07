#!/bin/bash
# 데스크탑 번들을 모노레포에 통합해 푸시 (서버에서 실행)
set -e
cd /data/suno-helper
git fetch /tmp/suno_helper.bundle master:suno-desktop
git fetch origin
git checkout -B release origin/main
git rm -r -q suno-helper 2>/dev/null || true
git read-tree --prefix=suno-helper/ -u suno-desktop
git commit -q -m "suno-helper: license server deployment + pubkey embedded (v1.0.0)"
git log --oneline -1
git push origin release:main
git checkout master 2>/dev/null || true
git branch -D suno-desktop || true
rm -f /tmp/suno_helper.bundle
echo PUSH_DONE
