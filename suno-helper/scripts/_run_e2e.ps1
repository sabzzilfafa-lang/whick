Start-Process -FilePath "C:\Users\user\suno_helper\backend\.venv\Scripts\python.exe" -ArgumentList "C:\Users\user\suno_helper\backend\run_server.py" -WorkingDirectory "C:\Users\user\suno_helper\backend" -WindowStyle Hidden
Start-Sleep -Seconds 6
& "C:\Users\user\suno_helper\backend\.venv\Scripts\python.exe" "C:\Users\user\suno_helper\scripts\test_local_api.py"
