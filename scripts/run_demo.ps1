# 데모(가상 데이터) 모드 실행 — 실제 사내 시스템에 연결하지 않습니다.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
Remove-Item Env:APP_MODE -ErrorAction SilentlyContinue
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
