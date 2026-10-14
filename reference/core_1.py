"""PoC 1: deterministic period comparison, no IFRS17 valuation logic."""
import csv
import io
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from .common import decode_utf8

REQUIRED = ('period', 'goc_id', 'product_code', 'contract_key', 'liability_balance')
KEYS = ('goc_id', 'product_code', 'contract_key')
MONTH = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')
MAX_BYTES = 5 * 1024 * 1024


def parse_csv(raw: bytes) -> list[dict]:
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError('CSV 파일은 1바이트 이상 5MB 이하여야 합니다.')
    reader = csv.DictReader(io.StringIO(decode_utf8(raw), newline=''))
    columns = reader.fieldnames or []
    missing = [name for name in REQUIRED if name not in columns]
    if missing:
        raise ValueError('필수 열 누락: ' + ', '.join(missing))
    result = []
    seen = set()
    for lineno, row in enumerate(reader, start=2):
        for name in REQUIRED:
            if not (row.get(name) or '').strip():
                raise ValueError(f'{lineno}행 {name}: 빈 값은 사용할 수 없습니다.')
        period = row['period'].strip()
        if not MONTH.fullmatch(period):
            raise ValueError(f'{lineno}행 period: YYYY-MM 형식이어야 합니다.')
        try:
            amount = Decimal(row['liability_balance'].strip())
            if not amount.is_finite():
                raise InvalidOperation()
        except (InvalidOperation, ValueError):
            raise ValueError(f'{lineno}행 liability_balance: 유한한 숫자여야 합니다.') from None
        cleaned = {k: (row.get(k) or '').strip() for k in REQUIRED}
        cleaned['liability_balance'] = amount
        cleaned['reason_code'] = (row.get('reason_code') or '').strip()
        identity = (period,) + tuple(cleaned[k] for k in KEYS)
        if identity in seen:
            raise ValueError(f'{lineno}행: 기간·GoC·상품·계약키 조합이 중복되었습니다.')
        seen.add(identity)
        result.append(cleaned)
    if not result:
        raise ValueError('분석할 데이터 행이 없습니다.')
    return result


def analyze(rows: list[dict], base: str, target: str, goc: str = '', product: str = '') -> dict:
    months = sorted({row['period'] for row in rows})
    if base not in months or target not in months or base >= target:
        raise ValueError('실제 파일에 있는 서로 다른 기간 중 기준월 < 비교월로 선택하세요.')
    filtered = [r for r in rows if (not goc or r['goc_id'] == goc) and (not product or r['product_code'] == product)]
    mapping = {(r['period'],) + tuple(r[k] for k in KEYS): r for r in filtered}
    identities = {tuple(r[k] for k in KEYS) for r in filtered if r['period'] in (base, target)}
    records = []
    by_goc, by_product = defaultdict(lambda: [Decimal(0), Decimal(0)]), defaultdict(lambda: [Decimal(0), Decimal(0)])
    start = end = Decimal(0)
    for key in sorted(identities):
        before = mapping.get((base,) + key)
        after = mapping.get((target,) + key)
        old = before['liability_balance'] if before else Decimal(0)
        new = after['liability_balance'] if after else Decimal(0)
        start += old
        end += new
        by_goc[key[0]][0] += old
        by_goc[key[0]][1] += new
        by_product[key[1]][0] += old
        by_product[key[1]][1] += new
        status = '신규' if not before else ('소멸' if not after else '계속')
        records.append({'goc_id': key[0], 'product_code': key[1], 'contract_key': key[2],
                        'base': old, 'target': new, 'delta': new-old, 'status': status,
                        'reason_code': (after or before)['reason_code']})
    records.sort(key=lambda r: (-abs(r['delta']), r['contract_key'], r['goc_id'], r['product_code']))
    def summary(by):
        return [{'group': k, 'base': v[0], 'target': v[1], 'delta': v[1]-v[0]} for k,v in sorted(by.items())]
    return {'base': start, 'target': end, 'delta': end-start, 'details': records,
            'by_goc': summary(by_goc), 'by_product': summary(by_product)}
