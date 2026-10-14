"""Offline diagnostic. Run: python preflight.py"""
from pathlib import Path
import importlib.util
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parent
print('== AI 심화교육 로컬 실습 준비 점검 ==')
print('Python:', sys.version.split()[0], 'OK' if sys.version_info >= (3,10) else '3.10 이상 필요')
print('Claude Code CLI:', shutil.which('claude') or '미발견 → 직접 설치/인증 확인')
print('Streamlit:', '설치됨' if importlib.util.find_spec('streamlit') else '미설치 → pip install -r requirements.txt')
files = [root/'app_1.py',root/'app_2.py',root/'app_3.py',root/'data/1안_가상_결산.csv',root/'data/2안_가상_실행.log',root/'data/2안_오류사전.csv']
for file in files:
    print('파일', 'OK' if file.exists() else 'MISSING', file.relative_to(root))
print('== 16개 규칙 기반 자동시험 ==')
result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=root)
if result.returncode:
    sys.exit(result.returncode)
print('16개 자동시험 통과. Streamlit 실제 브라우저/다운로드는 별도 수동 검증이 필요합니다.')
