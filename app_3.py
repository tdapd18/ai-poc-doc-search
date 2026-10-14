"""Streamlit PoC #3: local document evidence search (keyword based, no LLM).

Reads built-in fictional Markdown docs + fictional multi-format samples, and optional
uploads (md/docx/xlsx/pdf/hwpx) processed in memory only.
"""
from pathlib import Path
import streamlit as st
from reference.core_3 import load_docs, search
from reference.loaders_3 import SUPPORTED, load_bytes, load_folder

BASE = Path(__file__).resolve().parent / 'data'
MD_DIR = BASE / '3안_가상문서'
SAMPLE_DIR = BASE / '3안_다형식샘플'
EXAMPLES = ['RAFM E101이 발생하면?', 'GoC 단위 변동 분석 방법?',
            '결산 전 체크할 항목?', '휴가 규정의 육아휴직 수당은?']
SAMPLE_EXAMPLES = ['결산 승인 절차', 'A100 한도', '백업 주기 보안', 'RAFM 환경 점검']

st.set_page_config(page_title='3안 | 가상 업무문서 검색', layout='wide')
st.title('3안 | 가상 업무문서 근거 검색')
st.info('로컬 문서 검색(간이 PoC) · 키워드 기반 · 가상 데이터. '
        '실제 사내 규정 조회·최신성 보장·생성형 AI/RAG 답변이 아닙니다.')


@st.cache_data
def get_builtin():
    chunks = [{**c, 'format': 'md'} for c in load_docs(MD_DIR)]
    status = [{'파일': f, '형식': 'md', '상태': '성공', '문단 수': sum(c['file'] == f for c in chunks), '메시지': ''}
              for f in sorted({c['file'] for c in chunks})]
    if SAMPLE_DIR.is_dir():
        extra, extra_status = load_folder(SAMPLE_DIR)
        chunks += extra
        status += extra_status
    return chunks, status


@st.cache_data(show_spinner=False)
def parse_upload(name: str, data: bytes):
    return load_bytes(name, data)


def set_query(text: str):
    st.session_state['query'] = text


with st.sidebar:
    st.header('문서 소스')
    use_builtin = st.checkbox('내장 가상 문서 사용', value=True)
    uploads = st.file_uploader('가상 문서 업로드 (메모리에서만 처리, 저장 안 함)',
                               type=list(SUPPORTED), accept_multiple_files=True)
    st.caption('지원: .md .docx .xlsx .pdf .hwpx · 구형 .hwp·스캔본 PDF 미지원')
    st.warning('실제 사내·고객 문서는 업로드하지 마세요. 교육용 가상 문서만 사용합니다.')

chunks, status = [], []
if use_builtin:
    try:
        chunks, status = get_builtin()
    except ValueError as exc:
        st.error(str(exc))
    except OSError:
        st.error('가상 Markdown 문서 폴더가 없습니다. 키트의 루트에서 실행하세요.')
chunks = list(chunks)
status = list(status)
for up in uploads:
    try:
        got = parse_upload(up.name, up.getvalue())
        chunks += got
        status.append({'파일': up.name, '형식': got[0]['format'], '상태': '성공(업로드)', '문단 수': len(got), '메시지': ''})
    except ValueError as exc:
        status.append({'파일': up.name, '형식': Path(up.name).suffix.lstrip('.').lower(), '상태': '실패', '문단 수': 0, '메시지': str(exc)})

ok_files = sorted({c['file'] for c in chunks})
c1, c2, c3 = st.columns(3)
c1.metric('검색 방식', '키워드 기반')
c2.metric('문서 수', len(ok_files))
c3.metric('검색 문단 수', len(chunks))
with st.expander('문서 로딩 현황', expanded=any(s['상태'] == '실패' for s in status)):
    if status:
        st.dataframe(status, width='stretch', hide_index=True)
    failed = [s for s in status if s['상태'] == '실패']
    for s in failed:
        st.error(s['메시지'])

if not chunks:
    st.warning('검색할 문서가 없습니다. 내장 문서를 켜거나 가상 문서를 업로드하세요.')
    st.stop()

st.caption('예시 질문 (내장 .md)')
for col, example in zip(st.columns(len(EXAMPLES)), EXAMPLES):
    col.button(example, on_click=set_query, args=(example,), width='stretch', key='b_' + example)
st.caption('예시 질문 (다형식 샘플: docx · xlsx · pdf · hwpx)')
for col, example in zip(st.columns(len(SAMPLE_EXAMPLES)), SAMPLE_EXAMPLES):
    col.button(example, on_click=set_query, args=(example,), width='stretch', key='s_' + example)

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
            st.caption(f'파일: {result["file"]} ({result.get("format", "md")})  |  버전: {result["version"]}  |  '
                       f'분류: {result["category"]}  |  담당: {result["owner"]}  |  '
                       f'점수: {result["score"]}  |  일치어: {result["matched"]}')
            st.markdown('> ' + result['text'].replace('\n', ' '))
            st.code('원문 위치: ' + result['source'], language='text')
