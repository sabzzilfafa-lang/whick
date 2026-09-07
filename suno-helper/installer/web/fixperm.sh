#!/bin/bash
echo '=== before ==='
ls -la /mnt/music/whick-cc/solutions/suno-helper/
docker run --rm -v /mnt/music/whick-cc/solutions:/sol alpine sh -c 'chown -R 1000:1000 /sol/suno-helper && chmod -R a+rX /sol/suno-helper && echo FIXED'
echo '=== after ==='
ls -la /mnt/music/whick-cc/solutions/suno-helper/
echo '=== dl checks ==='
curl -s -o /dev/null -w "Setup.bat HTTP %{http_code} type=%{content_type} disp=%header{content-disposition}\n" "https://whick.org/dl/suno-helper/Setup.bat"
curl -s -o /dev/null -w "dl zip HTTP %{http_code}, %{size_download} bytes\n" "https://whick.org/dl/suno-helper/v1.1.0/wamss-current.zip" -r 0-1000
echo FIX_DONE
