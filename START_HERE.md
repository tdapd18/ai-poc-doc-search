# AI 심화교육 2026-10-14 | Claude Code 즉시착수 키트

> **핵심**: `data/`는 신규 제작한 100% 허구 데이터입니다. 실제 고객정보·회사자료·결산결과·실제 LOG·내부 규정·비밀번호를 Claude Code나 온라인 서비스에 제공하지 마세요. 이는 교육용 로컬 규칙 기반 PoC이며, 생성형 AI가 회계·모델 오류 원인을 판정하는 제품이 아닙니다.

## 먼저 확인할 것 (교육 당일 시작 전 10분)

1. 노트북에서 Python 3.10 이상, Claude Code CLI 설치·로그인 여부 확인(사용자 계정·교육 환경에 따라 절차 상이).
2. ZIP 전체 압축 해제 후 **키트 루트 디렉터리**에서 터미널 실행. `data/`, `reference/`, `app_1.py`가 함께 보여야 합니다.
3. 인터넷 또는 조직 정책 때문에 `pip install`이 제한될 수 있으므로 **전날 패키지 설치** 권장. 정상 동작은 로컬 가상 파일만으로 가능하고, 외부 AI API 키는 필요 없습니다.
4. Python 환경 만들기:
   - Windows PowerShell: `py -3 -m venv .venv` → `.venv\Scripts\Activate.ps1`
   - macOS/Linux: `python3 -m venv .venv` → `source .venv/bin/activate`
   - 공통: `python -m pip install -r requirements.txt`
5. 로직 테스트: `python -m unittest discover -s tests -v` (16건 전부 OK가 목표).
6. 데모 실행(각기 다른 터미널 또는 순차 실행):
   - `python -m streamlit run app_1.py --server.address 127.0.0.1 --server.port 8501`
   - `python -m streamlit run app_2.py --server.address 127.0.0.1 --server.port 8502`
   - `python -m streamlit run app_3.py --server.address 127.0.0.1 --server.port 8503`
   - 브라우저: http://127.0.0.1:8501, :8502, :8503
7. **Claude Code로 직접 만들기**: `prompts/`의 방안별 `.md` 전문을 Claude Code에 전달하고, 원본 가상 데이터 및 테스트를 기준으로 앱 작성·수정을 요청하세요. 앱 3개는 독립 PoC이며, 하나가 실패해도 다른 도구를 시연할 수 있습니다.

## 폴더별 역할

- `app_1.py`, `app_2.py`, `app_3.py`: 교육 당일 실행/수정 가능한 **참고 UI 시작 코드**(Streamlit).
- `reference/core_*.py`, `reference/common.py`: 계산·파싱·검색 규칙을 고정한 로컬 예제 구현.
- `tests/test_core.py`: **16개 자동 단위테스트**. Claude Code가 앱을 다시 만들더라도 동일한 기대 결과를 유지해야 합니다.
- `data/`: 정상·예외·신규/소멸 샘플. 데이터 명칭과 회사 시스템은 무관합니다.
- `prompts/`: 방안별 상세 개발 지시문. 구현 마감/검증 기준을 포함합니다.
- `DECISIONS.md`: 개발 중 이견을 방지하는 상세 결정사항.
- `DEMO_SCRIPT.md`: 각 도구 시연 순서와 예상 수치.

## 개발/검증 결과 구분

- **사전 검증됨**: 제공한 핵심 처리 코드에서 16개 단위 테스트가 모두 통과함(생성일 기준).
- **교육 노트북에서 확인해야 함**: `pip install`, Streamlit 서버 기동, 브라우저 UI 작동, Claude Code CLI 접근, 파일 다운로드 기능. 제작 시점에 Streamlit 실행 환경이 제공되지 않아 브라우저 실동작은 미검증입니다.
- **완료로 간주하는 시점**: 각 도구마다 ‘기능 화면 수동 확인 + 16개 테스트 OK + 정상/예외 시연 + 실제 사내정보 0건’ 조건을 만족할 때.
- **실행 불가 시 대안**: UI가 작동하지 않아도 코어 테스트 결과와 명시된 예시 입출력을 보고 시연·설명할 수 있으나, 이 경우 웹앱 PoC가 완성되었다고 표현하지 않습니다.

## 범위 및 기대치

- 1안: 가상 잔액의 월별 산술 비교. IFRS17 보험부채 측정과 회계 원인 진단이 아님.
- 2안: **실제 RAFM 전용 파서가 아닌 허구 오류코드 규칙 기반 분석기**. 원인 후보·점검 순서만 표시.
- 3안: 로컬 Markdown 키워드 검색. 임베딩/RAG/문서 권한/최신성 검증 기능은 없음.
- 하루 안에 3개 앱을 모두 개선·발표하는 경우 시간 및 환경에 따라 결과가 달라질 수 있으므로 **2안 → 3안 → 1안** 우선순위를 권장합니다.
