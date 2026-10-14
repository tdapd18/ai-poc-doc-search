"""Streamlit PoC #3: local Markdown evidence search (keyword based, no LLM)."""
from pathlib import Path
import streamlit as st
from reference.core_3 import load_docs, search

DOC_DIR = Path(__file__).resolve().parent / 'data' / '3안_가상문서'
EXAMPLES = ['RAFM E101이 발생하면?', 'GoC 단위 변동 분석 방법?',
            '결산 전 체크할 항목?', '휴가 규정의 육아휴직 수당은?']

st.set_page_config(page_title='3안 | 가상 업무문서 검색', layout='wide')
st.title('3안 | 가상 업무문서 근거 검색')
st.info('로컬 문서 검색(간이 PoC) · 키워드 기반 · 가상 데이터. '
        '실제 사내 규정 조회·최신성 보장·생성형 AI/RAG 답변이 아닙니다.')


@st.cache_data
def get_chunks(folder: str):
    return load_docs(Path(folder))


def set_query(text: str):
    st.session_state['query'] = text


try:
    chunks = get_chunks(str(DOC_DIR))
except ValueError as exc:
    st.error(str(exc))
    st.stop()
except OSError:
    st.error('가상 Markdown 문서 폴더가 없습니다. 키트의 루트에서 실행하세요.')
    st.stop()

docs = sorted({c['file'] for c in chunks})
c1, c2, c3 = st.columns(3)
c1.metric('검색 방식', '키워드 기반')
c2.metric('가상 문서 수', len(docs))
c3.metric('검색 문단 수', len(chunks))
with st.expander('로드된 가상 문서 목록'):
    seen = {}
    for c in chunks:
        seen.setdefault(c['file'], c)
    for name, c in seen.items():
        st.write(f'- `{name}` · {c["title"]} · 버전 {c["version"]} · {c["category"]} · 담당 {c["owner"]}')

st.caption('예시 질문')
for col, example in zip(st.columns(len(EXAMPLES)), EXAMPLES):
    col.button(example, on_click=set_query, args=(example,), use_container_width=True)

query = st.text_input('가상 문서에 질문해 보세요', key='query',
                      placeholder='예: E101 점검 / GoC 증감 / 결산 전 체크할 항목')

if not query.strip():
    st.write('위 입력란에 질문을 입력하면 관련 근거 문단 최대 3개를 보여 줍니다.')
else:
    results = search(chunks, query)
    if not results:
        st.warning('관련 근거 없음 · 내용을 임의로 만들어 답하지 않습니다. 질문 또는 문서를 확인하세요.')
    else:
        st.success(f'근거 문단 {len(results)}건 (점수순, 최대 3건)')
        for index, result in enumerate(results, 1):
            st.subheader(f'{index}. {result["title"]} — {result["section"]}')
            st.caption(f'파일: {result["file"]}  |  버전: {result["version"]}  |  '
                       f'분류: {result["category"]}  |  담당: {result["owner"]}  |  '
                       f'점수: {result["score"]}  |  일치어: {result["matched"]}')
            st.markdown('> ' + result['text'].replace('\n', ' '))
            st.code('원문 위치: ' + result['source'], language='text')
