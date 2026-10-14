# 3안 | 가상 업무문서 근거 검색 (로컬 문서 검색 간이 PoC)

가상 Markdown 문서(`data/3안_가상문서/*.md`)에서 질문과 관련된 `##` 절을 찾아 **본문 인용 + 파일명 + 버전 + 절 제목**을 함께 보여 줍니다.

## 실행

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m py_compile app_3.py
python -m streamlit run app_3.py --server.address 127.0.0.1 --server.port 8503
```

브라우저: http://127.0.0.1:8503

## 구현 범위 (현재)
- 키워드 기반 검색(`reference/core_3.py`): 한글/영문/코드 토큰, 동의어 `체크할→점검`, `증감→변동`, 2개 토큰 또는 도메인 키워드(E###/GoC/RAFM/IFRS17) 일치, 점수순 Top3.
- 근거가 없으면 `관련 근거 없음`만 표시하며 답변을 생성하지 않음.
- 파일당 1MB 제한, UTF-8(BOM 허용), 메타데이터(`# 제목`, `- 버전:`, `- 분류:`, `- 담당자:`, `## 절`) 검증.
- 외부 네트워크·LLM API 호출 없음. 모든 문서는 가상 데이터.

## 한계
정확한 한국어 형태소 분석, 승인된 정본/접근 권한/문서 최신성 검증은 없습니다.

## 향후 확장 (현재 미구현)
- 임베딩 기반 유사도 검색
- 보안심사 후 LLM 근거 기반 답변 생성
