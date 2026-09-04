#!/bin/sh
set -euo pipefail

# CC 재설치 동의 API URL — envsubst로 nginx.conf 생성
CC_API_URL="${CC_API_URL:-https://admin.whick.org}"
CC_API_HOST="${CC_API_HOST:-admin.whick.org}"

export CC_API_URL CC_API_HOST

envsubst '${CC_API_URL} ${CC_API_HOST}' < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf
