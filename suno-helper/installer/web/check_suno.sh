#!/bin/bash
cd /data/whick-ai/2_control_center/git-home
cat > /tmp/chk.js <<'EOF'
const fs = require('fs');
global.window = {};
eval(fs.readFileSync('js/i18n-cats.js', 'utf8'));
const W = window.WAMSS_I18N || {};
console.log('cats langs:', Object.keys(W).join(','));
console.log('cats ko suno.hero.sub:', (W.ko && W.ko['suno.hero.sub']) ? 'YES(bad: would need merge)' : 'NO(good: separate keys)');
console.log('cats prod.soon ko:', W.ko && W.ko['prod.soon']);
EOF
node /tmp/chk.js
echo '--- suno.html live checks ---'
curl -s https://whick.org/suno.html > /tmp/suno_live.html
echo "bytes: $(wc -c < /tmp/suno_live.html)"
for t in 'SUNO_I18N_EXTRA' 'i18n-cats.js' 'i18n.js' 'langSel' 'account.html#sunoPcBox'; do
  printf '%s: %s\n' "$t" "$(grep -c "$t" /tmp/suno_live.html)"
done
echo '--- index.html modal live ---'
curl -s https://whick.org/ > /tmp/idx_live.html
for t in 'sunoModal' 'sunoModalFrame'; do
  printf '%s: %s\n' "$t" "$(grep -c "$t" /tmp/idx_live.html)"
done
rm -f /tmp/chk.js /tmp/suno_live.html /tmp/idx_live.html
echo CHECK_DONE
