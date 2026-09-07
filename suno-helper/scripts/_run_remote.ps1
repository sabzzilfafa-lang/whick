# suno.html 업로드 + index.html 모달 스크립트 실행
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\_convert.ps1 -LocalFile installer\web\add_suno_modal.sh -RemotePath /tmp/add_suno_modal.sh
cmd /c "scp -q c:\Users\user\suno_helper\installer\web\suno.html whick-server:/data/whick-ai/2_control_center/git-home/suno.html"
cmd /c "ssh whick-server ""bash /tmp/add_suno_modal.sh; rm -f /tmp/add_suno_modal.sh"""
