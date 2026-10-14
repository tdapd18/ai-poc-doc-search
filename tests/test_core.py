"""Execute: python -m unittest discover -s tests -v"""
import unittest
from pathlib import Path
from decimal import Decimal
from reference.core_1 import parse_csv, analyze
from reference.core_2 import load_catalog, diagnose
from reference.core_3 import load_docs, search

DATA = Path(__file__).resolve().parents[1] / 'data'

class TestPoc1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = parse_csv((DATA / '1안_가상_결산.csv').read_bytes())

    def test_baseline_totals_and_groups(self):
        r = analyze(self.rows, '2026-08', '2026-09')
        self.assertEqual((r['base'], r['target'], r['delta']), (Decimal(690), Decimal(707), Decimal(17)))
        self.assertEqual({x['group']: x['delta'] for x in r['by_product']}, {'A100':8,'B200':15,'C300':4,'D400':-10})
        self.assertEqual({x['group']: x['delta'] for x in r['by_goc']}, {'G1':23,'G2':-6})
        self.assertEqual(sum(x['delta'] for x in r['details']), r['delta'])

    def test_filter(self):
        r = analyze(self.rows, '2026-08', '2026-09', product='B200')
        self.assertEqual((r['base'],r['target'],r['delta']), (50,65,15))

    def test_missing_column(self):
        with self.assertRaisesRegex(ValueError,'필수 열 누락'):
            parse_csv((DATA / '1안_컬럼누락_오류테스트.csv').read_bytes())

    def test_duplicate_row(self):
        raw = (DATA/'1안_가상_결산.csv').read_bytes()
        with self.assertRaisesRegex(ValueError,'중복'):
            parse_csv(raw + b'2026-08,G1,A100,DEMO-C001,100,RATE\n')

    def test_outer_join_new_and_closed(self):
        rows = parse_csv((DATA/'1안_신규소멸_테스트.csv').read_bytes())
        r = analyze(rows,'2026-08','2026-09')
        self.assertEqual((r['base'],r['target'],r['delta']), (100,30,-70))
        self.assertEqual({x['status'] for x in r['details']}, {'신규','소멸'})

    def test_invalid_month(self):
        raw = b'period,goc_id,product_code,contract_key,liability_balance\n2026-13,G1,A100,C1,1\n'
        with self.assertRaisesRegex(ValueError, 'YYYY-MM'):
            parse_csv(raw)

class TestPoc2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = load_catalog((DATA / '2안_오류사전.csv').read_bytes())

    def test_four_codes_and_evidence_line_numbers(self):
        findings = diagnose((DATA/'2안_가상_실행.log').read_bytes(), self.cat)
        self.assertEqual([x['code'] for x in findings], ['E101','E207','E320','E999'])
        self.assertEqual([x['lines'][0] for x in findings], [2,3,4,5])
        self.assertEqual(findings[3]['cause'],'추가 확인 필요')
        self.assertEqual(findings[3]['check_steps'], [])

    def test_empty_log(self):
        with self.assertRaisesRegex(ValueError, '빈 파일'):
            diagnose((DATA/'2안_빈실행_오류테스트.log').read_bytes(), self.cat)

    def test_invalid_encoding(self):
        with self.assertRaisesRegex(ValueError,'UTF-8'):
            diagnose(b'\xff\xfe',self.cat)

    def test_pattern_without_code(self):
        result = diagnose(b'2026-10-10 [ERROR] INPUT_FILE_NOT_FOUND no code\n', self.cat)
        self.assertEqual(result[0]['code'],'E101')

    def test_info_line_is_not_error(self):
        self.assertEqual(diagnose(b'2026-10-10 [INFO] E101 mention only\n', self.cat), [])

class TestPoc3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks = load_docs(DATA/'3안_가상문서')

    def test_e101(self):
        hits = search(self.chunks, 'RAFM E101이 발생하면?')
        self.assertIn('RAFM',hits[0]['title'])
        self.assertIn('E101',hits[0]['text'])
        self.assertTrue(hits[0]['version'])

    def test_goc(self):
        hits = search(self.chunks, 'GoC 단위 변동 분석 방법?')
        self.assertIn('IFRS17',hits[0]['title'])

    def test_checklist(self):
        hits = search(self.chunks, '결산 전 체크할 항목?')
        self.assertIn('결산 점검 체크리스트',hits[0]['title'])

    def test_no_unsupported_answer(self):
        self.assertEqual(search(self.chunks, '휴가 규정의 육아휴직 수당은?'), [])

    def test_results_have_sources(self):
        hits = search(self.chunks, 'E101 점검')
        self.assertTrue(all(h['source'] and h['file'] and h['text'] and h['version'] for h in hits))

if __name__ == '__main__':
    unittest.main()
