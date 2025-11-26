# 커밋 메시지 수정 스크립트
$ErrorActionPreference = "Stop"

# rebase todo 파일 생성
$todoContent = "reword 593faa9`npick 760cef9`n"
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
$todoPath = Join-Path $PWD ".git\rebase-todo"
[System.IO.File]::WriteAllText($todoPath, $todoContent, $utf8NoBom)

# 커밋 메시지 파일 복사
$commitMsgPath = Join-Path $PWD "commit_msg_utf8_prev.txt"
$editMsgPath = Join-Path $PWD ".git\COMMIT_EDITMSG"
Copy-Item $commitMsgPath $editMsgPath -Force

Write-Host "Rebase 설정 완료" -ForegroundColor Green

