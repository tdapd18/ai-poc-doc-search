"""Streamlit PoC #2: synthetic RAFM run log diagnostics."""
from pathlib import Path
import streamlit as st
from reference.core_2 import load_catalog, diagnose
from reference.common import export_csv

st.set_page_config(page_title='2안 | 가상 RAFM 로그 진단', layout='wide')
st.title('2안 | 가상 RAFM LOG 진단 지원')
st.info('교육용 PoC · 허구 오류코드·로그만 사용 · 원인 후보를 안내할 뿐 실제 RAFM을 제어하거나 복구하지 않습니다.')
log_file = st.file_uploader('LOG 선택(미선택 시 가상 샘플)', type=['log', 'txt'])
rule_file = st.file_uploader('오류사전 CSV 선택(미선택 시 가상 샘플)', type=['csv'])
try:
    log = log_file.getvalue() if log_file else Path('data/2안_가상_실행.log').read_bytes()
    cat = rule_file.getvalue() if rule_file else Path('data/2안_오류사전.csv').read_bytes()
    findings = diagnose(log, load_catalog(cat))
    if not findings:
        st.warning('탐지할 오류가 없습니다. [ERROR]/[WARN] 로그 또는 가상 오류코드를 확인하세요.')
    else:
        a, b, c = st.columns(3)
        a.metric('탐지 코드', len(findings))
        b.metric('사전 등록', sum(f['severity'] != '미등록' for f in findings))
        c.metric('추가 확인 필요', sum(f['severity'] == '미등록' for f in findings))
        for f in findings:
            with st.expander(f"{f['code']} · {f['severity']} · {f['count']}회 · {', '.join(map(str, f['lines']))}행", expanded=True):
                st.write('**원인 후보**: ' + f['cause'])
                if f['check_steps']:
                    st.write('**점검 순서**: ' + ' → '.join(f['check_steps']))
                else:
                    st.warning('오류사전 미등록 · 원인을 추측하지 않습니다. 담당자에게 확인하세요.')
                st.code('\n'.join(f'{n}행 | {line}' for n, line in zip(f['lines'], f['evidence'])), language='text')
        records = [{'code': f['code'], 'severity': f['severity'], 'count': f['count'],
                    'line_numbers': ';'.join(map(str, f['lines'])), 'cause': f['cause'],
                    'check_steps': ' > '.join(f['check_steps'])} for f in findings]
        st.download_button('진단 결과 CSV 내려받기', export_csv(records, list(records[0])),
                           file_name='가상_RAFM_진단결과.csv', mime='text/csv')
except ValueError as exc:
    st.error(str(exc))
except OSError:
    st.error('가상 LOG/오류사전을 찾지 못했습니다. 키트의 루트에서 실행하세요.')
