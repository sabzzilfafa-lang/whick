#!/bin/bash
echo '=== /dl/ nginx block ==='
docker exec whick-git-web sh -c "sed -n '50,75p' /etc/nginx/conf.d/default.conf"
echo '=== dl root on host ==='
grep -rn 'dl' /data/whick-ai/2_control_center/docker-compose*.yml 2>/dev/null | grep -i 'volum\|:/var\|root' | head -6
docker inspect whick-git-web --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' | head -10
echo '=== find actual suno zip ==='
find /data/whick-ai -maxdepth 6 -name 'SunoHelper*.zip' 2>/dev/null | head -5
find /data/whick-ai -maxdepth 5 -type d -name '*suno*' 2>/dev/null | head -8
echo '=== auth endpoints in site-api ==='
docker exec whick-cc-site-api sh -c "grep -rohn 'app\.\(get\|post\)([^)]*' /app 2>/dev/null | head -30" 2>/dev/null | head -30
docker exec whick-cc-site-api sh -c "ls /app 2>/dev/null | head -20"
echo '=== how WAMSS download button works (index html) ==='
grep -n 'dl/connect\|download' /data/whick-ai/2_control_center/git-home/index.html | head -12
echo '=== git-home header nav rest ==='
sed -n '40,70p' /data/whick-ai/2_control_center/git-home/index.html
echo RECON2_DONE
