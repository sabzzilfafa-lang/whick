# Sync-push: bundle local master -> whick-server -> merge into monorepo -> push to GitHub
git bundle create "$env:TEMP\suno_helper.bundle" master
cmd /c "scp -q $env:TEMP\suno_helper.bundle whick-server:/tmp/suno_helper.bundle"
cmd /c "ssh whick-server ""cd /data/suno-helper && git fetch /tmp/suno_helper.bundle master:suno-desktop && git fetch origin && git checkout -B release origin/main && git rm -r -q suno-helper 2>/dev/null; git read-tree --prefix=suno-helper/ -u suno-desktop && git commit -q -m 'suno-helper: bidirectional lyric paraphrasing (en-first -> ko paraphrase)' && git push origin release:main; git checkout master 2>/dev/null; git branch -D suno-desktop; rm -f /tmp/suno_helper.bundle; echo PUSH_OK"""
git status --short
"LOCAL_CLEAN"
