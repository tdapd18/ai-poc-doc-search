# 계리 업무자료 AI 통합검색 Tool (교육용 PoC)

공유폴더 · 그룹웨어 · 업무시스템에 흩어진 **가상의** 계리 업무자료를 자연어로 통합 검색하고,
관련 원문 문단·근거 문서·원본 위치를 한 화면에서 확인하는 Streamlit 웹앱입니다.

> **교육용 PoC 범위**
> - 모든 자료는 `data/` 의 **직접 만든 가상 더미데이터**입니다. 실제 사내 시스템·인터넷·외부 API 에 연결하지 않습니다.
> - 기본 실행은 **로컬 검색 모드**(키워드 + 관련성 점수)입니다. 이 모드의 결과는 *AI 생성 답변이 아닙니다.*
> - **실제 LLM 은 연결되어 있지 않습니다.** AI 답변 모드는 인터페이스와 **Mock(테스트용)** 구현만 제공합니다.
> - 화면의 사용자 전환은 **가상 사용자**이며 실제 회사 인증(SSO/AD)이 아닙니다.

## 폴더 구조

```text
actuarial_ai_search/
├── app.py                 # Streamlit 3단 화면 (왼쪽: 자료·범위 / 가운데: 검색 / 오른쪽: 근거 문서)
├── conftest.py, pytest.ini
├── requirements.txt, .env.example
├── README.md, README_DEMO.md   # 실행법 / 시연·수동 테스트 시나리오
├── docs/
│   ├── DESIGN.md          # 설계, 점수 규칙, 보안 설계, 사내망 연동 시 추가 필요사항
│   └── TEST_RESULTS.md    # 자동 테스트 결과표 (입력조건 / 예상 / 실제 / 통과)
├── connectors/            # 저장소별 Connector (공통 인터페이스 base.py)
│   ├── base.py  shared_folder.py  groupware.py  business_system.py
├── core/
│   ├── models.py          # 공통 문서 스키마
│   ├── document_parser.py # 메타데이터 파싱, 문단 분할, 지시문 의심 탐지
│   ├── indexer.py         # SQLite 색인 (documents / chunks / source_status)
│   ├── text_utils.py      # 한국어 용어 정규화·동의어 확장
│   ├── search_engine.py   # 점수 산정, 권한 필터, 캐시 재검증
│   ├── access_control.py  # 가상 사용자·문서 ACL (기본 거부)
│   ├── sync_manager.py    # 신규/수정/삭제/버전/권한 변경 감지·색인 갱신
│   ├── answer_generator.py# 모드 A(로컬) / 모드 B(AI, 선택) RAG
│   ├── llm_client.py      # LLM 연결 인터페이스 + Mock (실제 호출 없음)
│   ├── history.py         # 이전 답변 내역 재검증
│   └── services.py, config.py, logging_utils.py, presentation.py
├── data/
│   ├── shared_folder/ groupware/posts/ business_system/records/   # 가상 문서 10건
│   ├── metadata/search_dictionary.json   # 동의어·불용어·별칭 사전
│   └── demo_users.json                   # 가상 사용자 3명
├── database/              # SQLite 색인 파일(index.db)이 자동 생성되는 위치 (git 제외)
└── tests/                 # pytest (자동 테스트 69건)
```

## Windows PC 실행 방법 (PowerShell)

Python 3.10 이상이 필요합니다. 저장소 루트(`ai-poc-doc-search`)에서 시작합니다.

```powershell
# 1) 프로젝트 폴더로 이동
cd actuarial_ai_search

# 2) 가상환경 생성 및 활성화
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
#   (실행 정책 오류 시: Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned)

# 3) 패키지 설치 (streamlit, pytest)
python -m pip install -r requirements.txt

# 4) 웹앱 실행 → 브라우저에서 http://127.0.0.1:8501
python -m streamlit run app.py

# 5) 자동 테스트 실행 (다른 터미널, 가상환경 활성화 후)
python -m pytest
#   결과표를 파일로 저장하려면:
python -m pytest --report-md docs/TEST_RESULTS.md
```

macOS/Linux 는 `python3 -m venv .venv && source .venv/bin/activate` 후 동일하게 실행합니다.
설치 외에는 인터넷이 필요하지 않습니다. 첫 실행 시 자동으로 색인(`database/index.db`)이 만들어집니다.

## 설정 (선택)

`.env.example` 을 `.env` 로 복사해 수정합니다. 환경변수로도 지정할 수 있습니다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `LLM_PROVIDER` | `none` | `none`(비활성) / `mock`(테스트용 가짜 LLM) / `internal`(사내 LLM — **미구현**) |
| `SEARCH_TOP_K` | `5` | 결과 문서 수(최대 5) |
| `DATA_DIR`, `INDEX_DB_PATH` | `data/`, `database/index.db` | 데이터·색인 경로 |

## 주요 기능

- 3개 저장소 통합 검색, 자연어 질문, 동의어(예: *RAFM 실행 오류 = 모델 에러 = 모델 실행 실패*), 분류·저장소 필터, 상위 5건, 원문 문단 표시
- 사용자별 접근권한(가상 사용자 3명): 비인가 문서는 검색·미리보기·AI 근거·건수·캐시·이전 답변 어디에도 나타나지 않음
- `색인 갱신` 버튼: 신규/수정/삭제/버전 변경/권한 변경 반영 (저장소 한 곳이 실패해도 나머지는 계속 동작, 실패 저장소는 화면에 표시)
- 문서 속 악성 지시문은 **실행하지 않고** 경고 표시 + AI 전달 제외
- 검색 방식·점수 규칙: [`docs/DESIGN.md`](docs/DESIGN.md) 와 `core/search_engine.py` 상단 주석

## 구현 현황 요약

| 구분 | 상태 |
|---|---|
| 웹앱, Connector 3종, 통합 검색, 권한, 동기화, 근거 확인 | 구현 및 자동 테스트 통과 |
| AI 답변 모드 | **인터페이스 + Mock 만 구현·테스트.** 실제 LLM 연결 없음 |
| 실제 사내망(SMB/그룹웨어/업무시스템/SSO) 연동, 자동 스케줄러 | **미구현 (후속 과제)** — `docs/DESIGN.md` §8 |
| Windows PC 실제 실행 | **미검증**(개발은 Linux/Python 3.13 에서 수행) |
