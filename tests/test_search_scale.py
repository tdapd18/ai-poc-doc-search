"""검색 속도 개선(정규화 텍스트 저장 + SQL 후보 추출)이 결과를 바꾸지 않았음을 기준 구현과 비교해 검증한다."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from core.indexer import Indexer
from core.models import Chunk, Document
from core.search_engine import SearchEngine
from core.text_utils import SearchDictionary, analyze_query, normalize_text

QUERIES = ["E101 오류 조치", "RAFM 모델 실행 오류", "모델 에러", "IFRS 17 결산 검증", "보험계약집단 변동 분석", "결산 일정 마감",
           "CSM 변동률 기준", "GoC 롤포워드", "휴가 규정의 육아휴직 수당은?", "규정", "허용 오차", "체크시트", "승인 절차 가정",
           "a_b 100%", "존재하지 않는 용어 xyz"]


def reference(engine, user, query, scope, filters=None):
    """기준 구현: 필터된 모든 문서의 모든 조각을 읽어 점수를 계산(사전 필터 없음)."""
    docs = engine.access.filter_documents(user, engine.indexer.list_documents())
    analysis = analyze_query(query, engine.dictionary)
    if not analysis.concepts:
        return []
    scored = [r for r in (engine._score_document(d, analysis, scope) for d in docs) if r]
    return engine._sort(scored, "relevance", True)


@pytest.mark.parametrize("scope", ["all", "name", "body"])
def test_prefilter_gives_identical_results_demo(svc, users, scope, rec):
    """입력조건: 데모 데이터에서 15개 질의(동의어·별칭·일반어·특수문자·결과 없음)를 3개 검색 대상으로 실행
    예상결과: 후보 추출 방식의 결과(문서 순서·점수·일치 위치·일치 건수)가 전체 조각 순회 기준 구현과 완전히 같음"""
    n = 0
    for q in QUERIES:
        got = svc.engine.search(users["admin"], q, top_k=20, scope=scope)
        ref = reference(svc.engine, users["admin"], q, scope)
        assert [r.doc_id for r in got.results] == [r.doc_id for r in ref[:20]], q
        assert [r.score for r in got.results] == [r.score for r in ref[:20]], q
        assert [[p.chunk_seq for p in r.passages] for r in got.results] == [[p.chunk_seq for p in r.passages] for r in ref[:20]], q
        assert got.total_matched == len(ref) or got.status == "no_results" and not ref, q
        n += len(ref)
    rec(f"scope={scope}: 질의 {len(QUERIES)}개, 기준 구현과 순위·점수·위치 일치 (일치 문서 합계 {n})")


def test_prefilter_gives_identical_results_real_share(make_real, win):
    """입력조건: 실제 모드 합성 공유(DOCX/XLSX/PPTX/PDF/CSV, 메타데이터 수준 문서 포함)에서 같은 비교
    예상결과: 기준 구현과 완전히 같은 결과"""
    from conftest import PROJECT  # noqa: F401
    from core.services import sync_with_audit
    svc = make_real(full_text=True)
    sync_with_audit(svc)
    user = svc.access.current_user()
    for q in ["E101 오류 조치", "허용 오차 롤포워드", "GoC 변동률", "RAFM 오류대응", "결산 마감", "검증결과 집계", "옛날 결산문서"]:
        for scope in ("all", "name", "body"):
            got = svc.engine.search(user, q, top_k=20, scope=scope)
            ref = reference(svc.engine, user, q, scope)
            assert [(r.doc_id, r.score) for r in got.results] == [(r.doc_id, r.score) for r in ref[:20]], (q, scope)


def test_prefilter_scores_only_candidate_chunks(svc, users, monkeypatch):
    """입력조건: 'E101' 한 단어 검색 시 점수 계산에 투입되는 조각 수
    예상결과: 전체 조각 수보다 훨씬 적은 후보 조각만 점수 계산(속도 개선의 근거)"""
    total_chunks = sum(len(svc.indexer.get_chunks(d.doc_id)) for d in svc.indexer.list_documents())
    seen = []
    orig = svc.engine._chunk_scores
    monkeypatch.setattr(svc.engine, "_chunk_scores", lambda chunks, a, th: (seen.append(len(chunks)), orig(chunks, a, th))[1])
    svc.engine.search(users["admin"], "E101")
    assert 0 < sum(seen) < total_chunks / 3


def test_normalization_signature_recomputed_when_dictionary_changes(tmp_path):
    """입력조건: 별칭 사전이 바뀐 뒤 같은 색인을 새 사전의 엔진으로 열기
    예상결과: 저장된 정규화 텍스트가 자동으로 다시 계산되어, 새 사전 기준으로 검색됨 ('IFRS 17' ↔ 'ifrs17')"""
    d1 = SearchDictionary({"alias_normalization": {"ifrs 17": "ifrs17"}})
    d0 = SearchDictionary({})
    idx = Indexer(tmp_path / "i.db")
    eng = SearchEngine(idx, _admin_access(), d1)
    doc = Document("N-1", "제목", "shared_folder", "공유폴더", "기타", "1", "2026-01-01", "2026-01-01", "d", "\\\\s\\x\\a.txt",
                   "IFRS 17 결산 검증 문서의 본문입니다", segments=(("제목", "줄 1", "IFRS 17 결산 검증 문서의 본문입니다"),))
    idx.apply_changes("shared_folder", [doc], [])
    idx.set_source_status("shared_folder", "공유폴더", True)
    u = _admin_access().users()[0]
    assert eng.search(u, "ifrs17").results  # 별칭 사전: 'IFRS 17' → 'ifrs17'
    assert idx.get_chunks("N-1")[0].norm_text.startswith("ifrs17")
    eng0 = SearchEngine(idx, _admin_access(), d0)  # 별칭 없는 사전 → 자동 재계산
    assert idx.get_chunks("N-1")[0].norm_text.startswith("ifrs 17")
    assert not eng0.search(u, "ifrs17").results  # 별칭이 없으면 'ifrs17' 은 'ifrs 17' 과 일치하지 않는다


def _admin_access():
    from core.access_control import AccessController, User
    return AccessController([User("admin", "a", "", "admin", ())])


def test_candidate_chunks_escape_sql_wildcards(tmp_path):
    """입력조건: 질의 용어에 %, _, 역슬래시가 포함된 경우의 후보 추출
    예상결과: 와일드카드로 해석되지 않고 문자 그대로만 일치 (예: 'a_b' 는 'axb' 와 일치하지 않음)"""
    idx = Indexer(tmp_path / "i.db")
    docs = [Document(f"E-{i}", "t", "shared_folder", "공유폴더", "기타", "1", "2026-01-01", "2026-01-01", "d", f"\\\\s\\x\\{i}.txt",
                     text, segments=(("h", "줄 1", text),)) for i, text in enumerate(
        ["값은 100% 입니다 충분히 긴 문장", "값은 100 입니다 충분히 긴 문장", "a_b 라는 이름 충분히 긴 문장", "axb 라는 이름 충분히 긴 문장",
         "경로 c:\\temp 충분히 긴 문장", "경로 c:/temp 충분히 긴 문장"])]
    idx.apply_changes("shared_folder", docs, [])
    assert set(idx.candidate_chunks(["100%"])) == {"E-0"}
    assert set(idx.candidate_chunks(["a_b"])) == {"E-2"}
    assert set(idx.candidate_chunks(["c:\\temp"])) == {"E-4"}
    assert idx.candidate_chunks([]) == {} and idx.candidate_chunks(["존재하지않음"]) == {}


def test_list_documents_does_not_load_bodies(svc):
    """입력조건: 문서 목록 조회 / 단건 조회 / include_body 옵션
    예상결과: 목록에는 본문이 없고(검색마다 전체 본문을 읽지 않음), 단건 조회와 옵션 지정 시에는 본문 포함"""
    listed = svc.indexer.list_documents()
    assert listed and all(d.body == "" for d in listed)
    one = svc.indexer.get_document(listed[0].doc_id)
    assert one.body
    assert all(d.body for d in svc.indexer.list_documents(include_body=True))


def test_benchmark_smoke_small(tmp_path):
    """입력조건: 합성 문서 1,500건(조각 5개)을 색인하고 선택적/광범위/결과 없음 질의 실행
    예상결과: 정상 동작하고 아주 넉넉한 시간 안에 응답(성능 회귀 감시용 — 실제 성능은 tools/benchmark_search.py 로 측정)"""
    import benchmark_search as b
    idx, dic, _ = b.build(1500, 5, tmp_path / "b.db")
    eng = SearchEngine(idx, _admin_access(), dic)
    u = _admin_access().users()[0]
    t0 = time.perf_counter()
    broad = eng.search(u, "결산 검증 오류", top_k=10)
    none = eng.search(u, "존재하지않는용어xyz", top_k=10)
    assert broad.total_matched == 1500 and len(broad.results) == 10 and none.status == "no_results"
    assert time.perf_counter() - t0 < 15
