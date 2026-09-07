#!/bin/bash
echo '=== auth.html token storage ==='
grep -n 'localStorage\|wamss_git_token\|sessionStorage' /data/whick-ai/2_control_center/git-home/auth.html | head -10
echo '=== auth.html me/profile fetch ==='
grep -n 'fetch(\|/api/' /data/whick-ai/2_control_center/git-home/auth.html | head -15
echo '=== account.html me fetch (token usage) ==='
grep -n '/api/\|sGetTok\|Authorization' /data/whick-ai/2_control_center/git-home/account.html | head -15
echo AUTH_RECON_DONE
