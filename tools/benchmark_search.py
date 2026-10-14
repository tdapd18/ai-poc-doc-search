"""검색 성능 벤치마크(합성 데이터). 실제 PC/공유 성능을 대표하지 않으며, 구조적 병목 확인용이다.

  python tools/benchmark_search.py [문서수=20000] [문서당 조각수=5]
"""
from __future__ import annotations

import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.access_control import AccessController, User  # noqa: E402
from core.indexer import Indexer  # noqa: E402
from core.models import Document  # noqa: E402
from core.search_engine import SearchEngine  # noqa: E402
from core.text_utils import SearchDictionary, normalize_text  # noqa: E402

WORDS = ("결산 검증 모델 실행 오류 변동 분석 가정 변경 승인 일정 마감 보고서 점검 대사 잔액 계약 집단 CSM 이행현금흐름 "
         "위험조정 롤포워드 상품 담보 해지율 사업비 할인율 시나리오 파라미터 입력 파일 경로 권한 결과 요약 확인 절차 기준").split()


def build(n_docs: int, n_chunks: int, db: Path):
    dictionary = SearchDictionary.from_file(ROOT / "data" / "metadata" / "search_dictionary.json")
    idx = Indexer(db)
    idx.ensure_normalization(dictionary.signature(), lambda t: normalize_text(t, dictionary))
    rnd = random.Random(7)
    docs = []
    for i in range(n_docs):
        segs = tuple(("소제목", f"줄 {j * 3 + 1}", " ".join(rnd.choices(WORDS, k=40))) for j in range(n_chunks))
        docs.append(Document(f"B-{i:06d}", f"문서 {i} {rnd.choice(WORDS)}", "shared_folder", "공유폴더", "기타", "-", "2026-01-01",
                             "2026-09-01", "팀", f"\\\\srv\\sh\\폴더{i % 50}\\문서{i}.docx", "\n".join(s[2] for s in segs),
                             segments=segs, file_type="docx", file_name=f"문서{i}.docx", share="벤치"))
    t0 = time.perf_counter()
    for k in range(0, n_docs, 2000):
        idx.apply_changes("shared_folder", docs[k:k + 2000], [])
    idx.set_source_status("shared_folder", "공유폴더", True)
    return idx, dictionary, time.perf_counter() - t0


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    c = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    with tempfile.TemporaryDirectory() as td:
        idx, dic, t_index = build(n, c, Path(td) / "b.db")
        user = User("u", "u", "", "admin", ())
        eng = SearchEngine(idx, AccessController([user]), dic)
        print(f"문서 {n:,}건 × 조각 {c} = {n * c:,}개 색인 소요 {t_index:.1f}s")
        for q in ("결산 검증 오류", "ifrs17", "롤포워드 대사 잔액", "존재하지않는용어xyz"):
            t0 = time.perf_counter()
            r = eng.search(user, q, top_k=10)
            dt = time.perf_counter() - t0
            print(f"  '{q}': {dt * 1000:8.0f} ms  결과 {len(r.results)}건 / 일치 {r.total_matched:,}건")
