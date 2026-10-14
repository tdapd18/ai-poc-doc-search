import re
from datetime import date

import pytest

from conftest import FINANCE_DOCS
from core.indexer import Indexer
from core.presentation import folder_of, path_html, make_snippet, safe_highlight_html
from core.search_engine import DEFAULT_TOP_K, MAX_TOP_K, location_key
from helpers import make_xlsx, write_sidecar

Q = "E101 오류 조치"  # PDF(p.2) / Excel(오류내역 시트) / PPT(슬라이드 3) / 게시글 / 업무시스템에 모두 나타나는 용어


def _locs(resp):
    return {r.doc_id: [p.loc for p in r.passages] for r in resp.results}


def test_locations_per_file_type(svc, users, rec):
    """입력조건: 'E101 오류 조치' 검색(계리평가팀, 결과 20건까지)
    예상결과: PDF 는 'p.2', Excel 은 "시트 '오류내역' · 셀 …", PowerPoint 는 '슬라이드 3', Markdown 은 '줄 N'
    형태의 원문 위치가 결과에 표시됨"""
    r = svc.engine.search(users["actuary"], Q, top_k=20)
    locs = _locs(r)
    rec({k: v[:2] for k, v in locs.items() if k.startswith("SF-1")})
    assert any(re.fullmatch(r"p\.\d", x) for x in locs["SF-101"])
    assert "p.2" in locs["SF-101"]
    assert any(re.fullmatch(r"시트 '오류내역' · 셀 A\d:C\d", x) for x in locs["SF-102"])
    assert "슬라이드 3" in locs["SF-103"]
    r2 = svc.engine.search(users["actuary"], "IFRS17 결산 검증 절차", top_k=20)
    assert any(re.fullmatch(r"줄 \d+(–\d+)?", x) for x in _locs(r2)["SF-001"])
    assert all(x for v in locs.values() for x in v)  # 위치 표기가 빈 문서 없음


def test_result_fields_for_list_display(svc, users):
    """입력조건: 검색 결과 한 건
    예상결과: 문서명, 파일 형식, 수정일, 원본 UNC 경로(공유폴더), 공유 이름이 모두 채워져 있음"""
    r = next(x for x in svc.engine.search(users["actuary"], Q, top_k=20).results if x.doc_id == "SF-101")
    assert (r.title, r.file_type, r.modified_at, r.share) == ("결산 내부통제 점검 보고서 (2026년 9월)", "pdf",
                                                              "2026-10-08", "계리평가 공유")
    assert r.location.startswith("\\\\fs-actu01.example.invalid\\계리평가\\") and r.file_name.endswith(".pdf")
    assert r.hit_count >= 1 and r.passages[0].text


def test_file_type_filter(svc, users, rec):
    """입력조건: 문서 유형 필터 pdf / xlsx+pptx / 존재하지 않는 조합
    예상결과: 선택한 유형의 문서만 반환, 해당 없으면 no_results"""
    a = svc.engine.search(users["actuary"], Q, top_k=20, file_types=["pdf"])
    assert a.results and {r.file_type for r in a.results} == {"pdf"}
    b = svc.engine.search(users["actuary"], Q, top_k=20, file_types=["xlsx", "pptx"])
    rec(sorted((r.doc_id, r.file_type) for r in b.results))
    assert {r.file_type for r in b.results} == {"xlsx", "pptx"}
    assert svc.engine.search(users["actuary"], "GoC 변동 분석", file_types=["txt"]).status == "no_results"


def test_location_filter_multi_share(svc, users, rec):
    """입력조건: 위치 필터 — 계리평가 공유만 / 계리평가+재무팀 공유 / 그룹웨어만
    예상결과: 선택한 위치(공유)의 문서만 결과에 포함 (다중 경로 검색)"""
    q = "결산 마감 일정 점검"
    only = svc.engine.search(users["actuary"], q, top_k=20, locations=["shared_folder:계리평가 공유"])
    assert only.results and {r.share for r in only.results} == {"계리평가 공유"}
    both = svc.engine.search(users["actuary"], q, top_k=20,
                             locations=["shared_folder:계리평가 공유", "shared_folder:재무팀 공유"])
    rec(sorted({r.share for r in both.results}))
    assert {r.share for r in both.results} == {"계리평가 공유", "재무팀 공유"}
    gw = svc.engine.search(users["actuary"], q, top_k=20, locations=["groupware"])
    assert gw.results and {r.source_key for r in gw.results} == {"groupware"}


def test_modified_date_filter(svc, users, rec):
    """입력조건: 수정일 범위 — 2026-10-06 이후 / 2026-09-01~2026-09-30 / 날짜 객체와 문자열 모두
    예상결과: 경계일 포함으로 범위 안의 문서만 반환"""
    q = "결산 검증 모델 오류"
    r = svc.engine.search(users["admin"], q, top_k=20, modified_from="2026-10-06")
    rec(sorted((x.doc_id, x.modified_at) for x in r.results))
    assert r.results and all(x.modified_at >= "2026-10-06" for x in r.results)
    assert any(x.modified_at == "2026-10-06" for x in r.results)  # 경계 포함
    r2 = svc.engine.search(users["admin"], q, top_k=20, modified_from=date(2026, 9, 1), modified_to=date(2026, 9, 30))
    assert r2.results and all("2026-09-01" <= x.modified_at <= "2026-09-30" for x in r2.results)
    assert svc.engine.search(users["admin"], q, modified_from="2030-01-01").status == "no_results"


def test_filters_combine(svc, users):
    """입력조건: 유형 + 위치 + 분류 + 수정일 필터를 동시에 적용
    예상결과: 모든 조건을 동시에 만족하는 문서만 반환"""
    r = svc.engine.search(users["actuary"], "결산 오류", top_k=20, file_types=["pdf", "pptx"],
                          locations=["shared_folder:계리평가 공유"], categories=["결산"], modified_from="2026-10-01")
    assert r.results
    for x in r.results:
        assert x.file_type in ("pdf", "pptx") and x.share == "계리평가 공유" and x.category == "결산"
        assert x.modified_at >= "2026-10-01"


def test_scope_name_vs_body(svc, users, rec):
    """입력조건: 검색 대상 — 파일명만 / 본문만 / 통합
    예상결과: 파일명만: 본문에만 있는 용어(E101)는 결과 없음, 파일명 용어('체크시트')는 문서 발견(본문 위치 없음).
    본문만: 파일명에만 있는 용어('체크시트')는 결과 없음"""
    assert svc.engine.search(users["actuary"], "E101", scope="name").status == "no_results"
    assert svc.engine.search(users["actuary"], "E101", scope="body").results
    name = svc.engine.search(users["actuary"], "체크시트", scope="name")
    rec(f"파일명만 '체크시트' → {[r.doc_id for r in name.results]}")
    assert [r.doc_id for r in name.results] == ["SF-201"] and name.results[0].name_match
    assert name.results[0].passages == ()
    assert svc.engine.search(users["actuary"], "체크시트", scope="body").status == "no_results"
    both = svc.engine.search(users["actuary"], "체크시트", scope="all")
    assert both.results[0].doc_id == "SF-201"


def test_filename_search_hits_file_name_not_only_title(svc, users):
    """입력조건: 제목에는 없고 파일명에만 있는 단어('킥오프_자료' → '킥오프')가 아닌 파일명 토큰으로 검색
    예상결과: 'GoC_단위_변동분석_매뉴얼' 처럼 밑줄로 이어진 파일명 형태로 검색해도 문서를 찾음"""
    r = svc.engine.search(users["actuary"], "GoC_단위_변동분석_매뉴얼", scope="name")
    assert r.results and r.results[0].doc_id == "SF-002"


@pytest.mark.parametrize("sort,key", [("modified", lambda r: r.modified_at), ("name", lambda r: (r.file_name or r.title).casefold()),
                                      ("path", lambda r: r.location.casefold()), ("type", lambda r: r.file_type)])
def test_sorting(svc, users, sort, key):
    """입력조건: 정렬 기준 수정일/파일명/경로/형식, 오름·내림차순
    예상결과: 결과 전체가 해당 기준으로 단조 정렬됨"""
    q = "결산 검증 모델 오류 일정"
    asc = svc.engine.search(users["admin"], q, top_k=20, sort=sort, descending=False).results
    desc = svc.engine.search(users["admin"], q, top_k=20, sort=sort, descending=True).results
    assert len(asc) >= 6 and len(desc) == len(asc)
    if sort != "type":  # 형식 정렬은 같은 형식끼리 순서가 같아 정확한 역순이 아닐 수 있다
        assert [r.doc_id for r in asc] == [r.doc_id for r in reversed(desc)]
    ks = [key(r) for r in asc]
    assert ks == sorted(ks)
    kd = [key(r) for r in desc]
    assert kd == sorted(kd, reverse=True)


def test_relevance_sort_default_and_reverse(svc, users):
    """입력조건: 관련도 정렬 내림/오름
    예상결과: 내림차순은 점수 큰 순, 오름차순은 반대"""
    d = svc.engine.search(users["admin"], "결산 검증 오류", top_k=20)
    a = svc.engine.search(users["admin"], "결산 검증 오류", top_k=20, descending=False)
    assert [r.score for r in d.results] == sorted((r.score for r in d.results), reverse=True)
    assert [r.doc_id for r in a.results] == [r.doc_id for r in reversed(d.results)]


def test_top_k_choices(svc, users, rec):
    """입력조건: 결과 수 5(기본) / 10 / 20 / 1000
    예상결과: 기본 5건, 일치 문서가 더 있으면 10건까지 확장, 상한 20 초과 요청은 20 으로 제한, total_matched 는 전체 일치 수"""
    d = svc.engine.search(users["admin"], "결산")
    big = svc.engine.search(users["admin"], "결산", top_k=10)
    huge = svc.engine.search(users["admin"], "결산", top_k=1000)
    rec(f"기본 {len(d.results)}건 / 10 → {len(big.results)}건 / 총 일치 {d.total_matched}건")
    assert DEFAULT_TOP_K == 5 and len(d.results) == 5 and d.total_matched > 5
    assert len(big.results) == min(10, big.total_matched) and len(huge.results) <= MAX_TOP_K == 20


def test_filter_changes_do_not_reuse_stale_cache(svc, users):
    """입력조건: 같은 검색어를 필터만 바꿔 연속 검색
    예상결과: 캐시가 필터별로 분리되어 각각 올바른 결과 반환"""
    a = svc.engine.search(users["actuary"], Q, top_k=20)
    b = svc.engine.search(users["actuary"], Q, top_k=20, file_types=["pdf"])
    c = svc.engine.search(users["actuary"], Q, top_k=20)
    assert len(b.results) < len(a.results) and c.from_cache and not b.from_cache


# ---- 권한 -----------------------------------------------------------------
def test_new_documents_respect_acl(svc, users, rec):
    """입력조건: 재무팀 사용자가 PDF/Excel/PPT 문서가 있는 주제를 검색, 계리 전용 Excel(SF-102)·관리자 문서 포함
    예상결과: 재무팀 권한 문서(SF-101/103/201/202 등)만 나오고 SF-102·SF-004 는 어떤 필터/정렬에서도 노출되지 않음"""
    seen = set()
    for kw in ({}, {"file_types": ["xlsx"]}, {"sort": "name"}, {"scope": "name"}, {"locations": ["shared_folder:계리평가 공유"]}):
        for q in (Q, "모델별 검증결과 집계", "예외 승인 내역", "GoC별 변동 CSM"):
            seen |= {r.doc_id for r in svc.engine.search(users["finance"], q, top_k=20, **kw).results}
    rec(f"재무팀 결과 문서 합집합: {sorted(seen)}")
    assert seen <= FINANCE_DOCS and not seen & {"SF-102", "SF-004"}


def test_matching_chunks_navigation_and_acl(svc, users, rec):
    """입력조건: 문서 안 일치 위치 목록 조회(미리보기의 이전/다음 이동 근거)
    예상결과: 문서 순서의 일치 위치 목록(PDF p.2 포함), 검색어 없음/비인가 사용자는 빈 목록"""
    m = svc.engine.matching_chunks(users["actuary"], "SF-101", "E101 오류")
    rec(m)
    assert [x[0] for x in m] == sorted(x[0] for x in m) and "p.2" in [x[1] for x in m]
    assert svc.engine.matching_chunks(users["finance"], "SF-102", "E101") == []
    assert svc.engine.matching_chunks(users["actuary"], "SF-101", "  ") == []
    assert svc.engine.matching_chunks(users["actuary"], "NOPE", "E101") == []


def test_acl_revoke_on_pdf_via_sidecar(svc, users, data_copy):
    """입력조건: PDF 의 메타데이터 파일에서 재무팀 권한을 회수하고 색인 갱신
    예상결과: 권한변경으로 감지, 재무팀 검색·원문 미리보기에서 사라짐 (바이너리 문서에도 권한 재검증 적용)"""
    assert any(r.doc_id == "SF-101" for r in svc.engine.search(users["finance"], "내부통제 점검 보고서").results)
    side = data_copy / "shared_folder" / "계리평가" / "결산검증" / "결산_내부통제_점검보고서.pdf.meta.json"
    text = side.read_text(encoding="utf-8").replace('"finance"', '"actuarial"')
    side.write_text(text, encoding="utf-8")
    rep = svc.sync.sync()
    assert next(s for s in rep.sources if s.source_key == "shared_folder").acl_changed == ["SF-101"]
    assert all(r.doc_id != "SF-101" for r in svc.engine.search(users["finance"], "내부통제 점검 보고서").results)
    assert svc.engine.open_document(users["finance"], "SF-101") is None


# ---- 동기화(새 형식) --------------------------------------------------------
def test_xlsx_add_modify_delete_sync(svc, users, data_copy, rec):
    """입력조건: 공유폴더에 Excel 추가 → 셀 값 수정 → 파일 삭제 후 각각 색인 갱신
    예상결과: 추가 시 셀 위치와 함께 검색, 수정 시 최신 값으로 교체, 삭제 시 결과에서 제거"""
    p = data_copy / "shared_folder" / "계리평가" / "모델검증" / "신규_집계.xlsx"
    make_xlsx(p, {"집계": [["항목", "건수"], ["가정변경요청", 3]]})
    write_sidecar(p, doc_id="SF-500", title="신규 집계표", category="기타", allowed_groups=["actuarial"])
    assert next(s for s in svc.sync.sync().sources if s.source_key == "shared_folder").added == ["SF-500"]
    r = svc.engine.search(users["actuary"], "가정변경요청")
    assert r.results[0].doc_id == "SF-500" and r.results[0].passages[0].loc == "시트 '집계' · 셀 A2:B2"
    rec(r.results[0].passages[0].loc)
    make_xlsx(p, {"집계": [["항목", "건수"], ["사업비변경요청", 7]]})
    rep = svc.sync.sync()
    assert next(s for s in rep.sources if s.source_key == "shared_folder").updated == ["SF-500"]
    assert not svc.engine.search(users["actuary"], "가정변경요청").results
    assert svc.engine.search(users["actuary"], "사업비변경요청").results[0].doc_id == "SF-500"
    p.unlink()
    svc.sync.sync()
    assert svc.indexer.get_document("SF-500") is None and not svc.engine.search(users["actuary"], "사업비변경요청").results


def test_old_index_schema_is_rebuilt(tmp_path, data_copy):
    """입력조건: 이전 버전 스키마의 색인 DB 파일 위에서 앱 시작
    예상결과: 오류 없이 새 스키마로 재생성(파생 데이터이므로 비우고 재색인), 이후 정상 색인·검색"""
    import sqlite3
    from core.services import build_services
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    c.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT); INSERT INTO meta VALUES('schema_version','1');"
                    "CREATE TABLE documents(doc_id TEXT PRIMARY KEY);")
    c.commit()
    c.close()
    s = build_services(data_copy, db)
    assert s.indexer.count_documents() == 0
    s.sync.sync()
    assert s.indexer.count_documents() == 15
    assert isinstance(s.indexer, Indexer)


# ---- 표시 보조 -------------------------------------------------------------
def test_snippet_centers_on_match_and_highlights_safely(rec):
    """입력조건: 긴 본문 중간에 검색어가 있는 텍스트, HTML 태그가 섞인 텍스트
    예상결과: 일치 위치 주변만 '…'과 함께 발췌되고 일치 단어가 강조되며 HTML 은 이스케이프됨"""
    text = "앞부분 " * 40 + "RAFM 실행 오류가 발생하면 <b>조치</b>하십시오 " + "뒷부분 " * 60
    s = make_snippet(text, ["오류"])
    out = safe_highlight_html(s, ["오류"])
    rec(s[:50])
    assert s.startswith("…") and s.endswith("…") and "오류" in s and len(s) < 220
    assert "<mark>오류</mark>" in out and "<b>" not in out and "&lt;b&gt;" in out
    assert make_snippet("짧은 본문", ["없음"]) == "짧은 본문"


def test_location_key_and_folder_of(svc):
    """입력조건: 공유폴더/그룹웨어 문서의 위치 키, UNC 경로의 상위 폴더 계산
    예상결과: 공유는 'shared_folder:표시이름', 그 외는 저장소 키, 상위 폴더 경로는 파일명 제외"""
    assert location_key(svc.indexer.get_document("SF-101")) == "shared_folder:계리평가 공유"
    assert location_key(svc.indexer.get_document("GW-001")) == "groupware"
    assert folder_of("\\\\fs\\a\\b\\c.pdf") == "\\\\fs\\a\\b"


def test_unc_path_html_keeps_double_backslash():
    """입력조건: UNC 경로를 마크다운 안의 HTML 로 출력
    예상결과: 역슬래시가 문자 참조로 바뀌어 마크다운 이스케이프에 의해 줄어들지 않고, HTML 특수문자는 이스케이프됨"""
    out = path_html("\\\\fs\\a<b>\\c.pdf")
    assert "\\" not in out and out.startswith("&#92;&#92;fs") and "&lt;b&gt;" in out
