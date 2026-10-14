"""PoC 2: simulated error catalog diagnostics; never controls RAFM."""
import csv
import io
import re
from collections import defaultdict
from .common import decode_utf8

MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_RULE_BYTES = 1 * 1024 * 1024
CODE = re.compile(r'\b(E\d{3})\b', flags=re.I)
LEVEL = re.compile(r'\[(ERROR|WARN|WARNING|FATAL)\]', flags=re.I)
ORDER = {'높음': 0, '중간': 1, '낮음': 2, '미등록': 3}
REQUIRED = ('code', 'pattern', 'severity', 'cause', 'check_steps')


def load_catalog(raw: bytes) -> dict:
    if not raw or len(raw) > MAX_RULE_BYTES:
        raise ValueError('오류사전 CSV는 1MB 이하여야 합니다.')
    reader = csv.DictReader(io.StringIO(decode_utf8(raw), newline=''))
    missing = [k for k in REQUIRED if k not in (reader.fieldnames or [])]
    if missing:
        raise ValueError('오류사전 필수 열 누락: ' + ', '.join(missing))
    catalog = {}
    for lineno, row in enumerate(reader, 2):
        code = (row.get('code') or '').strip().upper()
        if not CODE.fullmatch(code):
            raise ValueError(f'사전 {lineno}행: 코드 형식이 잘못되었습니다.')
        if code in catalog:
            raise ValueError(f'사전 {lineno}행: 코드 중복 {code}')
        if row['severity'].strip() not in ('높음', '중간', '낮음'):
            raise ValueError(f'사전 {lineno}행: 심각도 값은 높음/중간/낮음 중 하나입니다.')
        if any(not (row.get(k) or '').strip() for k in REQUIRED):
            raise ValueError(f'사전 {lineno}행: 필수 값이 비어 있습니다.')
        catalog[code] = {k: row[k].strip() for k in REQUIRED}
    if not catalog:
        raise ValueError('오류사전에 항목이 없습니다.')
    return catalog


def diagnose(raw: bytes, catalog: dict) -> list[dict]:
    if not raw or len(raw) > MAX_LOG_BYTES:
        raise ValueError('LOG는 빈 파일이 아니어야 하며 2MB 이하여야 합니다.')
    lines = decode_utf8(raw).splitlines()
    found = defaultdict(lambda: {'lines': [], 'evidence': []})
    for n, line in enumerate(lines, 1):
        if not LEVEL.search(line):
            continue
        codes = set(c.upper() for c in CODE.findall(line))
        if not codes:
            for code, entry in catalog.items():
                if entry['pattern'].casefold() in line.casefold():
                    codes.add(code)
        for code in sorted(codes):
            found[code]['lines'].append(n)
            found[code]['evidence'].append(line)
    outputs = []
    for code, rows in found.items():
        entry = catalog.get(code)
        severity = entry['severity'] if entry else '미등록'
        outputs.append({'code': code, 'severity': severity, 'count': len(rows['lines']),
                        'lines': rows['lines'], 'evidence': rows['evidence'],
                        'cause': entry['cause'] if entry else '추가 확인 필요',
                        'check_steps': entry['check_steps'].split(' > ') if entry else []})
    outputs.sort(key=lambda row: (ORDER[row['severity']], row['lines'][0], row['code']))
    return outputs
