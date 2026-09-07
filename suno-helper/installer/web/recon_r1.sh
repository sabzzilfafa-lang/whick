#!/bin/bash
echo '=== nginx /dl/ route ==='
docker exec whick-git-web sh -c "grep -rn 'location /dl' /etc/nginx/ 2>/dev/null" | head -6
echo '=== CC suno package dir ==='
ls -la /data/whick-ai/2_control_center/packages/suno-helper/ 2>/dev/null | head -10
echo '=== find wamss-current for suno ==='
find /data/whick-ai/2_control_center -maxdepth 4 -name '*current*zip' 2>/dev/null | head -8
echo '=== nav login/logout in index.html ==='
grep -n 'login\|logout\|account.html' /data/whick-ai/2_control_center/git-home/index.html | head -10
echo '=== how account.html serves download (if any) ==='
grep -no '/dl/[a-zA-Z0-9/_.-]*\|/api/[a-z/-]*download[a-z/-]*\|solution[^"]*zip' /data/whick-ai/2_control_center/git-home/account.html | head -8
echo '=== site-api auth me endpoint (name guess) ==='
docker exec whick-cc-site-api sh -c "grep -rn \"'/api/auth\|\\\"/api/auth\" /app/*.js 2>/dev/null | head -8" 2>/dev/null || echo skip
echo '=== WAMSS_I18N nav keys (for reuse) ==='
grep -o '"nav\.[a-zA-Z]*"' /data/whick-ai/2_control_center/git-home/js/i18n-cats.js | sort -u | head -20
echo '=== header html of index.html (for wrapper reuse) ==='
sed -n '1,40p' /data/whick-ai/2_control_center/git-home/index.html
echo RECON_DONE
