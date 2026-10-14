# 실제 모드 체험(샌드박스): 회사 공유폴더 없이 합성 Windows 공유로 실제 모드 화면을 써 봅니다.
#   .\scripts\run_real_sandbox.ps1   → http://127.0.0.1:8502
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -m streamlit run scripts/real_sandbox_app.py --server.address 127.0.0.1 --server.port 8502
