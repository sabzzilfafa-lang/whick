#!/bin/bash
# status 문자열이 JS 안의 것이라 HTML 엔티티가 아닌 \u 이스케이프로 존재 — 브라우저 실행 시 정상 표시됨.
# 확인: JS 이스케이프 형태로 존재하는지
curl -s https://whick.org/account.html | grep -c '\\ub4f1\\ub85d\\ub41c PC'
echo "(위 숫자가 1 이상이면 JS가 브라우저에서 '등록된 PC가 없습니다...'로 표시함)"
# 계정페이지가 로드되는지 HTTP 상태
curl -s -o /dev/null -w "account.html HTTP %{http_code}\n" https://whick.org/account.html
curl -s -o /dev/null -w "suno/status API HTTP %{http_code}\n" https://whick.org/api/suno/status
echo FINAL_DONE
