$rr = (Get-Content installer\web\check_served.sh -Raw) -replace "`r`n","`n"
[System.IO.File]::WriteAllText("$env:TEMP\cs6.sh", $rr, (New-Object System.Text.UTF8Encoding($false)))
cmd /c "scp -q %TEMP%\cs6.sh whick-server:/tmp/cs6.sh && ssh whick-server ""bash /tmp/cs6.sh; rm -f /tmp/cs6.sh"""
