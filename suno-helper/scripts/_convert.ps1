$rr = (Get-Content installer\web\check_served.sh -Raw) -replace "`r`n","`n"
[System.IO.File]::WriteAllText("$env:TEMP\cs7.sh", $rr, (New-Object System.Text.UTF8Encoding($false)))
cmd /c "ssh whick-server ""bash /tmp/cs7.sh 2>/dev/null; rm -f /tmp/cs7.sh"""
git ls-remote origin main
