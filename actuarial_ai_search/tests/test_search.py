import pytest

from core.search_engine import MAX_TOP_K
from core.text_utils import SearchDictionary, analyze_query

# (질문, 기대 문서) — 기대 문서가 상위 3위 안에 있어야 한다
QUESTIONS = [
    ("RAFM 모델 실행 오류가 나면 어떻게 대응하나요?", "GW-001"),
    ("GoC 단위 변동 분석은 어떻게 하나요?", "SF-002"),
    ("월말 결산 일정과 마감 시한은?", "GW-002"),
    ("계리적 가정을 변경할 때 승인 절차는?", "SF-003"),
    ("결산 검증 결과 불일치 건은 무엇인가요?", "BS-002"),
    ("모델별 검증 체크리스트 알려줘", "BS-003"),
    ("IFRS17 결산 검증 절차", "SF-001"),
    ("RAFM 실행 이력에서 E207 에러 확인", "BS-001"),
]


def test_expected_documents_found(svc, users, rec):
    """입력조건: 정상 업무 질문 8개 (계리평가팀 사용자)
    예상결과: 8개 모두 기대 문서가 상위 3위 이내 (기준: 5개 중 4개 이상 → 상위 기준 충족)"""
    hit, detail = 0, []
    for q, expected in QUESTIONS:
        ids = [r.doc_id for r in svc.engine.search(users["actuary"], q).results[:3]]
        hit += expected in ids
        detail.append(f"{expected}:{'O' if expected in ids else 'X'}")
    rec(f"{hit}/{len(QUESTIONS)} 적중 ({', '.join(detail)})")
    assert hit >= 7 and hit >= 4


@pytest.mark.parametrize("q", ["RAFM 실행 오류", "모델 에러", "모델 실행 실패", "모델 장애 대응"])
def test_synonyms_find_rafm_faq(svc, users, q, rec):
    """입력조건: 'RAFM 실행 오류' / '모델 에러' / '모델 실행 실패' / '모델 장애 대응'
    예상결과: 유사 표현이라도 RAFM 오류 대응 FAQ(GW-001)가 1위"""
    r = svc.engine.search(users["actuary"], q)
    rec(f"1위={r.results[0].doc_id if r.results else None}")
    assert r.results and r.results[0].doc_id == "GW-001"


def test_alias_normalization(svc, users):
    """입력조건: 'IFRS 17', '보험계약집단' 표기
    예상결과: 'IFRS17', 'GoC' 문서와 동일하게 검색됨"""
    r1 = svc.engine.search(users["actuary"], "IFRS 17 결산 검증")
    assert r1.results and r1.results[0].doc_id == "SF-001"
    r2 = svc.engine.search(users["actuary"], "보험계약집단 변동 분석")
    assert r2.results and r2.results[0].doc_id == "SF-002"


def test_results_sorted_and_capped(svc, users):
    """입력조건: 여러 문서에 걸치는 질문
    예상결과: 점수 내림차순 정렬, 최대 5건, 각 결과에 점수/원본 위치/원문 문단 포함"""
    r = svc.engine.search(users["admin"], "결산 검증 모델 실행 오류 점검", top_k=50)
    scores = [x.score for x in r.results]
    assert scores == sorted(scores, reverse=True) and 1 <= len(r.results) <= MAX_TOP_K
    for x in r.results:
        assert x.location and x.passages and x.passages[0].text and x.score > 0


def test_category_and_source_filters(svc, users):
    """입력조건: 분류 필터(RAFM) 또는 저장소 필터(업무시스템)를 적용한 검색
    예상결과: 결과가 해당 분류/저장소 문서로만 구성"""
    r = svc.engine.search(users["actuary"], "모델 실행 오류 결산", categories=["RAFM"])
    assert r.results and {x.category for x in r.results} == {"RAFM"}
    r = svc.engine.search(users["actuary"], "모델 실행 오류 결산", sources=["business_system"])
    assert r.results and {x.source_key for x in r.results} == {"business_system"}
    r = svc.engine.search(users["actuary"], "GoC 변동 분석", categories=["결산"])
    assert all(x.category == "결산" for x in r.results)


def test_results_span_multiple_sources(svc, users, rec):
    """입력조건: 'RAFM 모델 실행 오류' (계리평가팀)
    예상결과: 그룹웨어·업무시스템 등 서로 다른 저장소의 문서가 한 결과 목록에 함께 표시"""
    r = svc.engine.search(users["actuary"], "RAFM 모델 실행 오류")
    systems = {x.source_system for x in r.results}
    rec(str(sorted(systems)))
    assert len(systems) >= 2


def test_no_results_for_unrelated_question(svc, users):
    """입력조건: 문서에 없는 주제(휴가 규정의 육아휴직 수당)
    예상결과: status=no_results, 결과 0건, 임의 생성 없음"""
    r = svc.engine.search(users["admin"], "휴가 규정의 육아휴직 수당은?")
    assert r.status == "no_results" and r.results == []


def test_empty_query_is_handled(svc, users):
    """입력조건: 빈 검색어 / 공백 / 의미 없는 기호
    예상결과: 예외 없이 안내 상태(empty_query / no_results)"""
    assert svc.engine.search(users["actuary"], "").status == "empty_query"
    assert svc.engine.search(users["actuary"], "   ").status == "empty_query"
    assert svc.engine.search(users["actuary"], "?!?!").status == "no_results"


def test_particles_and_endings_stripped():
    """입력조건: '오류가 발생하면', '결산은'
    예상결과: 조사/어미 제거 후 핵심 용어('오류', '발생', '결산')만 개념으로 추출"""
    d = SearchDictionary.from_file("data/metadata/search_dictionary.json")
    a = analyze_query("결산은 오류가 발생하면", d)
    assert [c.term for c in a.concepts] == ["결산", "오류", "발생"]
    err = next(c for c in a.concepts if c.term == "오류")
    assert "에러" in [t for t, _ in err.variants]


def test_no_documents_indexed_status(tmp_path, data_copy):
    """입력조건: 색인을 한 번도 만들지 않은 상태에서 검색
    예상결과: 'no_sources' 안내 (연결된 저장소/색인 없음), 예외 없음"""
    from core.services import build_services
    s = build_services(data_copy, tmp_path / "empty.db")
    r = s.engine.search(s.access.get_user("u_admin"), "결산")
    assert r.status == "no_sources" and r.results == []


def test_no_connectors_status(tmp_path, data_copy):
    """입력조건: 연결된 저장소(Connector)가 0개
    예상결과: 동기화/검색 모두 예외 없이 'no_sources'"""
    from core.services import build_services
    s = build_services(data_copy, tmp_path / "x.db", connectors=[])
    assert s.sync.sync().sources == []
    assert s.engine.search(s.access.get_user("u_admin"), "결산").status == "no_sources"
