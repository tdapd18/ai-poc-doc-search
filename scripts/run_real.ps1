# 실제 Windows 공유폴더 검색 모드 실행 (개인 PC, 현재 로그인 계정 권한 적용)
#   PowerShell:  .\scripts\run_real.ps1
# 처음 실행하면 '초기 설정' 화면이 열립니다: 보안 모드 → 공유폴더 등록 → 연결 테스트 → 색인 생성.
# 기본은 메타데이터 전용(파일 내용 미열람)입니다. 본문 검색은 회사 보안 승인 후 설정 화면에서만 켭니다.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$env:APP_MODE = "real"
# 설정·색인·감사 로그 위치(기본: %LOCALAPPDATA%\ActuarialDocSearch). 바꾸려면 아래 주석을 해제하세요.
# $env:APP_HOME = "$env:LOCALAPPDATA\ActuarialDocSearch"
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
