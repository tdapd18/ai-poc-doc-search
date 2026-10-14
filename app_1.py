"""Streamlit PoC #1: synthetic period-end movement analysis."""
from pathlib import Path
import streamlit as st
from reference.core_1 import parse_csv, analyze
from reference.common import export_csv

st.set_page_config(page_title='1안 | 가상 결산 증감', layout='wide')
st.title('1안 | 가상 결산 잔액 증감 분석')
st.info('교육용 PoC · 모든 입력은 신규 제작한 허구 데이터만 사용 · 실제 IFRS17 부채계산 또는 회계 판단이 아닙니다.')
upload = st.file_uploader('가상 결산 CSV 업로드 (선택: 미선택 시 기본 샘플)', type=['csv'])
try:
    raw = upload.getvalue() if upload else Path('data/1안_가상_결산.csv').read_bytes()
    rows = parse_csv(raw)
    periods = sorted({r['period'] for r in rows})
    if len(periods) < 2:
        st.warning('기간이 2개 이상 있는 CSV를 사용하세요.')
        st.stop()
    left, right = st.columns(2)
    with left:
        base = st.selectbox('기준월', periods, index=0)
    with right:
        target = st.selectbox('비교월', periods, index=len(periods)-1)
    col1, col2 = st.columns(2)
    with col1:
        goc = st.selectbox('GoC 필터', ['전체'] + sorted({r['goc_id'] for r in rows}))
    with col2:
        product = st.selectbox('상품 필터', ['전체'] + sorted({r['product_code'] for r in rows}))
    result = analyze(rows, base, target, '' if goc == '전체' else goc, '' if product == '전체' else product)
    a, b, c = st.columns(3)
    a.metric('기준월 잔액(가상 단위)', f"{result['base']:,.0f}")
    b.metric('비교월 잔액(가상 단위)', f"{result['target']:,.0f}")
    c.metric('증감(가상 단위)', f"{result['delta']:+,.0f}")
    tab1, tab2, tab3 = st.tabs(['GoC별', '상품별', '계약별 상세'])
    def display(data, group_name):
        return [{group_name: r['group'], '기준월': float(r['base']), '비교월': float(r['target']), '증감': float(r['delta'])} for r in data]
    with tab1:
        st.dataframe(display(result['by_goc'], 'GoC'), use_container_width=True, hide_index=True)
    with tab2:
        st.dataframe(display(result['by_product'], '상품'), use_container_width=True, hide_index=True)
    detailed = [{'GoC': r['goc_id'], '상품': r['product_code'], '가상계약키': r['contract_key'],
                 '기준월': float(r['base']), '비교월': float(r['target']), '증감': float(r['delta']),
                 '상태': r['status'], '가상사유코드': r['reason_code']} for r in result['details']]
    with tab3:
        st.dataframe(detailed, use_container_width=True, hide_index=True)
    st.download_button('계약별 결과 CSV 내려받기', export_csv(detailed, list(detailed[0]) if detailed else ['GoC', '상품', '가상계약키']),
                       file_name='가상_결산_증감_결과.csv', mime='text/csv')
    st.caption('신규·소멸 계약은 존재하지 않는 기간 잔액을 0으로 처리합니다. 사유코드는 확정된 원인 판정이 아닙니다.')
except ValueError as exc:
    st.error(str(exc))
except OSError:
    st.error('샘플 CSV를 찾을 수 없습니다. 키트의 루트 폴더에서 실행했는지 확인하세요.')
