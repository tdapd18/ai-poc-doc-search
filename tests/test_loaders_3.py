import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reference.core_3 import search  # noqa: E402
from reference.loaders_3 import load_bytes, load_folder  # noqa: E402

SAMPLES = ROOT / 'data' / '3안_다형식샘플'


class TestLoaders3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks, cls.status = load_folder(SAMPLES)

    def test_all_formats_load(self):
        self.assertEqual({s['형식'] for s in self.status}, {'docx', 'xlsx', 'pdf', 'hwpx'})
        self.assertTrue(all(s['상태'] == '성공' for s in self.status))

    def test_docx_section_and_metadata(self):
        hit = search(self.chunks, '결산 승인 절차')[0]
        self.assertEqual(hit['format'], 'docx')
        self.assertEqual(hit['section'], '결산 승인 절차')
        self.assertEqual(hit['version'], '2026-10 교육용')

    def test_xlsx_row_chunk(self):
        hit = search(self.chunks, 'A100 한도')[0]
        self.assertEqual(hit['format'], 'xlsx')
        self.assertIn('A100', hit['text'])
        self.assertEqual(hit['version'], '미상')

    def test_pdf_page_source(self):
        hit = search(self.chunks, '백업 주기 보안')[0]
        self.assertEqual(hit['format'], 'pdf')
        self.assertTrue(hit['source'].endswith('쪽'))

    def test_hwpx(self):
        hit = search(self.chunks, 'RAFM 환경 점검')[0]
        self.assertEqual(hit['format'], 'hwpx')
        self.assertIn('RAFM', hit['text'])

    def test_unsupported_and_corrupt(self):
        with self.assertRaises(ValueError):
            load_bytes('a.hwp', b'x')
        with self.assertRaises(ValueError):
            load_bytes('a.txt', b'x')
        for ext in ('docx', 'xlsx', 'pdf', 'hwpx'):
            with self.assertRaises(ValueError):
                load_bytes('bad.' + ext, b'not a real file')

    def test_unrelated_question_has_no_evidence(self):
        self.assertEqual(search(self.chunks, '휴가 규정의 육아휴직 수당은?'), [])


if __name__ == '__main__':
    unittest.main()
