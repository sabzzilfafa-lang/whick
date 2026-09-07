#!/bin/bash
# v1.1.0 디렉터리에 남은 이전 zip 삭제 후 빈 디렉터리 제거
B=/mnt/music/whick-cc/solutions/suno-helper
ls -la "$B/v1.1.0" 2>/dev/null
find "$B/v1.1.0" -type f -name '*.zip' -delete 2>/dev/null
rmdir "$B/v1.1.0" && echo "v1.1.0 removed"
ls -la "$B"
echo PURGE_DONE
