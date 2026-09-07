powershell -NoProfile -ExecutionPolicy Bypass -File scripts\_convert.ps1 -LocalFile scripts\check_account.sh -RemotePath /tmp/keymatch.sh
cmd /c "ssh whick-server ""bash /tmp/keymatch.sh; rm -f /tmp/keymatch.sh"""
