"""화면(검색 결과 중심 UI) 동작 테스트 — Streamlit AppTest 로 버튼·필터·선택을 실제 구동한다."""
from core.presentation import path_html


def _search(at, query, **opts):
    at.text_input(key="query_text").set_value(query)
    next(b for b in at.button if b.label == "검색").click().run()
    assert not at.exception
    return at.session_state["last"]["resp"]


def _md(at):
    return " ".join(m.value for m in at.markdown)


def _click(at, label_prefix):
    next(b for b in at.button if label_prefix in b.label).click().run()
    assert not at.exception


def test_three_panels_and_result_summary(app, rec):
    """입력조건: 앱 실행 후 검색
    예상결과: 왼쪽 '검색 범위 및 필터', 가운데 '검색 결과 N건', 오른쪽 '관련 원문 미리보기' 영역이 모두 표시됨"""
    at, _ = app
    md = _md(at)
    assert "검색 범위 및 필터" in md and "관련 원문 미리보기" in md
    _search(at, "E101 오류 조치")
    md = _md(at)
    assert "검색 결과 " in md and "건**" in md
    rec("3개 영역 제목 + 결과 건수 표시")


def test_rows_show_name_type_date_unc_and_locations(app, rec):
    """입력조건: 'E101 오류 조치' 검색, 결과 20건
    예상결과: 결과 행에 파일 형식 배지, 파일명, 수정일, 원본 UNC 경로, PDF 쪽/Excel 시트·셀/PPT 슬라이드 위치가 표시됨"""
    at, _ = app
    at.selectbox(key="top_k").select(20).run()
    _search(at, "E101 오류 조치")
    md = _md(at)
    # 마크다운 원문에는 역슬래시가 문자 참조로 들어간다 (렌더 결과의 역슬래시 2개는 브라우저 테스트가 검증)
    assert path_html("\\\\fs-actu01.example.invalid\\계리평가\\결산검증\\결산_내부통제_점검보고서.pdf") in md
    for needle in (">PDF<", ">XLSX<", ">PPTX<", "p.2", "시트 &#x27;오류내역&#x27; · 셀", "슬라이드 3",
                   "수정 2026-10-08", "원본 UNC 경로"):
        assert needle.replace("&#x27;", "'") in md.replace("&#x27;", "'"), needle
    rec("PDF p.2 / Excel 시트·셀 / PPT 슬라이드 3 / UNC / 수정일 표시 확인")


def test_filters_change_results_immediately(app, rec):
    """입력조건: 검색 후 문서 유형 필터(PDF)·위치 필터·수정일 프리셋을 차례로 변경 (검색 버튼 재클릭 없음)
    예상결과: 변경 즉시 결과가 필터에 맞게 다시 계산됨"""
    at, _ = app
    at.selectbox(key="top_k").select(20).run()
    base = len(_search(at, "E101 오류 조치").results)
    at.multiselect(key="f_types").set_value(["pdf"]).run()
    r = at.session_state["last"]["resp"]
    assert r.results and {x.file_type for x in r.results} == {"pdf"}
    at.multiselect(key="f_types").set_value([]).run()
    at.multiselect(key="f_locs").set_value(["shared_folder:계리평가 공유"]).run()
    r = at.session_state["last"]["resp"]
    assert r.results and {x.share for x in r.results} == {"계리평가 공유"}
    at.multiselect(key="f_locs").set_value([]).run()
    at.radio(key="date_preset").set_value("최근 7일").run()
    r = at.session_state["last"]["resp"]
    ref = "2026-10-12"  # 접근 가능한 자료 중 가장 최근 수정일 (계리평가팀 기준)
    assert r.results and all("2026-10-05" <= x.modified_at <= ref for x in r.results)
    rec(f"전체 {base}건 → PDF만 / 계리평가 공유만 / 최근 7일 필터가 즉시 반영")


def test_scope_and_sort_change_rerun_search(app):
    """입력조건: 검색 후 검색 대상을 '파일명만'으로, 정렬을 '파일명' 오름차순으로 변경
    예상결과: 같은 검색어로 즉시 다시 검색되어 파일명 일치 결과만 나오고 파일명순으로 정렬됨"""
    at, _ = app
    _search(at, "결산")
    at.radio(key="scope").set_value("name").run()
    r = at.session_state["last"]["resp"]
    assert r.results and all(x.name_match for x in r.results)
    at.selectbox(key="sort").select("name").run()
    at.toggle(key="sort_desc").set_value(False).run()
    names = [(x.file_name or x.title).casefold() for x in at.session_state["last"]["resp"].results]
    assert names == sorted(names)


def test_select_location_updates_preview_and_path(app, rec):
    """입력조건: PDF 결과의 '위치 열기' 버튼 선택
    예상결과: 오른쪽 미리보기에 해당 문서의 UNC 경로(복사용 코드 블록)·상위 폴더 경로가 나오고 선택 위치가 기록됨"""
    at, _ = app
    _search(at, "내부통제 점검 보고서 E101")
    assert at.session_state["last"]["resp"].results[0].doc_id == "SF-101"
    sel = at.session_state["selected"]
    assert sel[0] == "SF-101"
    codes = [c.value for c in at.code]
    assert codes[0] == "\\\\fs-actu01.example.invalid\\계리평가\\결산검증\\결산_내부통제_점검보고서.pdf"
    assert codes[1] == "\\\\fs-actu01.example.invalid\\계리평가\\결산검증"
    # 다른 문서의 위치를 선택하면 미리보기가 바뀐다
    _search(at, "E101 오류 조치")
    other = next(b for b in at.button if b.key and b.key.startswith("loc_SF-103"))
    other.click().run()
    assert at.session_state["selected"][0] == "SF-103"
    assert [c.value for c in at.code][0].endswith("월말결산_킥오프_자료.pptx")
    assert "슬라이드 3" in _md(at)
    rec("선택 문서에 따라 미리보기 경로 코드 블록 변경")


def test_prev_next_match_navigation(app, rec):
    """입력조건: 일치 위치가 여러 곳인 문서에서 '다음 일치'를 반복 클릭한 뒤 '이전 일치' 클릭
    예상결과: 선택 위치가 문서 순서대로(오름차순) 이동하다가 처음으로 순환하고, '이전 일치'는 한 칸 되돌아감"""
    at, _ = app
    _search(at, "RAFM 모델 실행 오류")
    doc, first = at.session_state["selected"]
    visited = [first]
    for _ in range(12):
        _click(at, "다음 일치")
        assert at.session_state["selected"][0] == doc
        seq = at.session_state["selected"][1]
        if seq == first:
            break
        visited.append(seq)
    rec(f"이동 순서(문단 번호): {visited} 후 처음으로 순환")
    assert len(visited) >= 3, "일치 위치가 여러 곳인 문서여야 한다"
    assert at.session_state["selected"][1] == first  # 순환 확인
    inc = visited[visited.index(min(visited)):]
    assert inc == sorted(inc)  # 문서 순서대로 증가
    _click(at, "이전 일치")
    assert at.session_state["selected"][1] == visited[-1]  # 처음에서 '이전' → 마지막 일치


def test_browse_list_before_search_and_reset_filters(app):
    """입력조건: 검색 전 첫 화면, 필터 지정 후 '필터 초기화'
    예상결과: 접근 가능한 문서 13건 목록(파일명·UNC 경로)이 보이고, 초기화하면 모든 필터가 해제됨"""
    at, _ = app
    md = _md(at)
    assert "문서 13건" in md and path_html("\\\\fs-fin01.example.invalid\\재무공유\\") in md
    at.multiselect(key="f_types").set_value(["pdf"]).run()
    assert "문서 1건" in _md(at)
    _click(at, "필터 초기화")
    assert at.session_state["f_types"] == [] and "문서 13건" in _md(at)


def test_location_options_hide_unauthorized_shares(app, rec):
    """입력조건: 계리팀 / 재무팀 / 관리자 사용자의 위치 필터 선택지
    예상결과: 접근 가능한 문서가 있는 위치만 노출 ('관리자 전용' 공유는 관리자에게만)"""
    at, _ = app
    opts = lambda: set(at.multiselect(key="f_locs").options)  # noqa: E731
    assert not any("관리자 전용" in o for o in opts())
    at.selectbox(key="user_id").select("u_finance").run()
    fin = opts()
    assert not any("관리자 전용" in o for o in fin) and not any("그룹웨어" == o for o in fin)
    at.selectbox(key="user_id").select("u_admin").run()
    assert any("관리자 전용" in o for o in opts())
    rec("재무팀 위치 선택지: " + ", ".join(sorted(fin)))


def test_share_registration_admin_only(app, rec):
    """입력조건: 일반 사용자 / 관리자 화면에서 공유폴더 등록 UI, 잘못된 UNC 와 올바른 UNC 등록
    예상결과: 일반 사용자에게는 등록 UI 없음, 관리자는 등록 가능(잘못된 UNC 는 오류 안내), 등록 후 새 공유 문서가 검색됨"""
    at, data = app
    assert not any("공유폴더(UNC) 등록" in e.label for e in at.expander)
    assert any("관리자만" in c.value for c in at.caption)
    new = data / "shared_folder" / "신계약팀"
    new.mkdir()
    (new / "메모.md").write_text(
        "---\ndoc_id: SF-300\ntitle: 신계약 점검 메모\ncategory: 기타\nversion: 1.0\ncreated_at: 2026-10-10\n"
        "modified_at: 2026-10-11\ndepartment: 신계약팀\nallowed_users: []\nallowed_groups: [actuarial]\n---\n"
        "# 신계약 점검 메모\n\n신계약 데이터 마감 전에 확인할 항목을 정리한 가상의 메모입니다.\n", encoding="utf-8")
    at.selectbox(key="user_id").select("u_admin").run()
    assert any("공유폴더(UNC) 등록" in e.label for e in at.expander)

    def register(name, unc):
        next(t for t in at.text_input if t.label == "표시 이름").set_value(name)
        next(t for t in at.text_input if t.label == "UNC 경로").set_value(unc)
        next(b for b in at.button if b.label == "등록").click().run()

    register("신계약팀 공유", "C:\\temp")
    assert any("UNC 경로 형식" in e.value for e in at.error)
    register("신계약팀 공유", "\\\\fs-new01.example.invalid\\신계약")
    assert any("등록했습니다" in s.value for s in at.success)
    at.selectbox(key="user_id").select("u_actuary").run()
    r = _search(at, "신계약 점검 메모")
    assert r.results[0].doc_id == "SF-300" and r.results[0].location == "\\\\fs-new01.example.invalid\\신계약\\메모.md"
    rec(r.results[0].location)


def test_unauthorized_document_never_shown_in_ui(app):
    """입력조건: 재무팀으로 전환해 계리 전용 문서(Excel SF-102, FAQ)가 걸리는 질문 검색
    예상결과: 결과·미리보기·경로 코드 블록 어디에도 비인가 문서 경로/제목이 나타나지 않음"""
    at, _ = app
    at.selectbox(key="user_id").select("u_finance").run()
    at.selectbox(key="top_k").select(20).run()
    _search(at, "모델별 검증결과 집계 E101 오류 조치 RAFM")
    page = _md(at) + " ".join(c.value for c in at.code)
    assert "모델별_검증결과" not in page and "GW-001" not in page and "RAFM 모델 실행 오류 대응 FAQ" not in page
    assert "fs-adm01" not in page


def test_ai_mode_mock_still_available_with_locations(app):
    """입력조건: AI 답변 모드 + Mock LLM 으로 검색
    예상결과: Mock 고지 문구와 출처 버튼([n] 문서명 · 위치)이 표시되고, 실제 AI 가 아니라는 표시 유지"""
    at, _ = app
    at.toggle(key="mode_ai").set_value(True).run()
    at.checkbox(key="use_mock").set_value(True).run()
    _search(at, "GoC 단위 변동 분석은 어떻게 하나요?")
    md = _md(at)
    assert "Mock 구조 테스트 응답" in md and "실제 생성형 AI가 만든 답변이 아니며" in md
    assert any(b.label.startswith("[1] ") and ("줄" in b.label or "슬라이드" in b.label or "p." in b.label)
               for b in at.button)
