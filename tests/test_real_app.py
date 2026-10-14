"""실제 모드 화면(초기 설정 → 연결 테스트 → 색인 → 검색) — AppTest + 합성 Windows 공유."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from winshare import PHRASE, UNC_ROOT  # noqa: E402

streamlit_testing = pytest.importorskip("streamlit.testing.v1")
PROJECT = Path(__file__).resolve().parent.parent


@pytest.fixture
def real_app(win, tmp_path, monkeypatch):
    monkeypatch.setenv("APP_MODE", "real")
    monkeypatch.setenv("APP_HOME", str(tmp_path / "apphome"))
    monkeypatch.setenv("USERDOMAIN", "CORP")
    monkeypatch.setenv("USERNAME", "tester")
    monkeypatch.setattr("core.services.LocalFS", lambda *a, **k: win.fs)  # 실제 OS 대신 합성 Windows 공유를 사용
    monkeypatch.chdir(PROJECT)
    import streamlit
    from streamlit.testing.v1 import AppTest
    streamlit.cache_resource.clear()
    at = AppTest.from_file(str(PROJECT / "app.py"), default_timeout=90).run()
    assert not at.exception, [e.value for e in at.exception]
    return at, win, tmp_path / "apphome"


def md(at):
    return " ".join(m.value for m in at.markdown)


def click(at, key=None, label=None):
    b = at.button(key=key) if key else next(b for b in at.button if b.label == label)
    b.click().run()
    assert not at.exception, [e.value for e in at.exception]


def register(at, name, unc, excl=""):
    next(t for t in at.text_input if t.label == "표시 이름").set_value(name)
    next(t for t in at.text_input if t.label == "UNC 경로").set_value(unc)
    next(t for t in at.text_input if t.label.startswith("제외할")).set_value(excl)
    click(at, label="공유폴더 등록")


def test_first_run_opens_setup_with_safe_defaults(real_app, rec):
    """입력조건: 실제 모드 첫 실행(등록된 공유 없음)
    예상결과: 초기 설정 화면이 열리고, 현재 Windows 계정 표시, 기본 보안 모드는 메타데이터 전용, 가상 사용자 선택은 없음"""
    at, win, home = real_app
    assert at.session_state["page"] == "setup"
    page = md(at)
    assert "초기 설정" in " ".join(t.value for t in at.title) and "CORP\\tester" in " ".join(c.value for c in at.caption)
    assert "현재: **메타데이터 전용**" in page and at.radio(key="setup_mode_choice").value == "metadata_only"
    assert not any(s.label == "가상 사용자 선택" for s in at.selectbox)
    assert "⬜ 공유폴더 등록" in page and "⬜ 색인 생성" in page
    rec("첫 실행: 설정 화면, 기본 메타데이터 전용")


def test_register_validation_messages(real_app):
    """입력조건: 잘못된 UNC·관리자 공유·정상 경로·중복 경로를 차례로 등록
    예상결과: 오류는 안내 문구로 표시되고 정상 경로만 등록됨"""
    at, win, _ = real_app
    register(at, "공유", "C:\\temp")
    assert any("UNC 경로 형식" in e.value for e in at.error)
    register(at, "공유", "\\\\srv\\C$")
    assert any("관리자 공유" in e.value for e in at.error)
    register(at, "계리평가팀", UNC_ROOT, "Archive*, 개인*")
    assert any("등록했습니다" in s.value for s in at.success)
    assert any("제외 패턴: Archive*, 개인*" in c.value for c in at.caption)
    register(at, "중복", UNC_ROOT + "\\하위")
    assert any("겹치는" in e.value for e in at.error)


def test_connection_test_then_index_in_metadata_only(real_app, rec):
    """입력조건: 공유 등록 → 연결 테스트 → 색인 생성(메타데이터 전용)
    예상결과: 연결 테스트 전에는 색인 버튼이 비활성, 테스트 성공 후 활성화, 색인 중 파일 내용 읽기 0회, 완료 후 문서 수 표시"""
    at, win, home = real_app
    register(at, "계리평가팀", UNC_ROOT)
    assert at.button(key="setup_run_index").disabled
    click(at, key="setup_test_all")
    assert any("연결 성공" in s.value for s in at.success) and not at.button(key="setup_run_index").disabled
    assert any("파일 내용을 읽지 않았습니다" in c.value for c in at.caption)
    click(at, key="setup_run_index")
    assert any("색인 생성을 마쳤습니다" in s.value for s in at.success)
    assert win.fs.reads == [] and len(win.fs.opens) > 10
    assert "✅ 색인 생성" in md(at)
    rec(f"본문 읽기 {len(win.fs.reads)}회, 열기 확인 {len(win.fs.opens)}회")


def test_connection_failures_show_guidance_and_block_indexing(real_app):
    """입력조건: 오프라인 / 접근 거부 공유에서 연결 테스트
    예상결과: 원인별 조치 안내가 표시되고 색인 생성은 막힘"""
    at, win, _ = real_app
    register(at, "계리평가팀", UNC_ROOT)
    win.fs.offline(UNC_ROOT)
    click(at, key="setup_test_all")
    assert any("연결 테스트 실패" in e.value for e in at.error) and any("VPN" in c.value for c in at.caption)
    assert at.button(key="setup_run_index").disabled
    win.fs.offline(UNC_ROOT, False)
    win.fs.deny_list(UNC_ROOT)
    click(at, key="setup_test_all")
    assert any("권한" in e.value for e in at.error)
    assert at.button(key="setup_run_index").disabled


def _ready_metadata(at):
    register(at, "계리평가팀", UNC_ROOT)
    click(at, key="setup_test_all")
    click(at, key="setup_run_index")
    at.radio(key="page").set_value("search").run()
    assert not at.exception


def test_search_page_in_metadata_mode(real_app, rec):
    """입력조건: 색인 후 검색 화면에서 파일명으로 검색, 본문 용어로 검색
    예상결과: 메타데이터 전용 배너, Windows 계정 표시, 결과에 UNC 경로와 '본문 미색인' 배지, 본문 용어는 결과 없음"""
    at, win, _ = real_app
    _ready_metadata(at)
    page = md(at)
    assert "메타데이터 전용 모드" in page and "CORP\\tester" in page and "색인 수준: 메타데이터 전용" in page
    at.text_input(key="query_text").set_value("검증결과 집계")
    next(b for b in at.button if b.label == "검색").click().run()
    page = md(at)
    assert "&#92;&#92;fs-corp01.example.invalid&#92;계리평가팀&#92;" in page and "본문 미색인" in page
    at.text_input(key="query_text").set_value(PHRASE)
    next(b for b in at.button if b.label == "검색").click().run()
    assert any("관련 문서를 찾지 못했습니다" in i.value for i in at.info)
    rec("메타 전용: 파일명 검색 성공, 본문 문구 검색은 결과 없음")


def test_full_text_switch_requires_acknowledgement_and_resets(real_app, rec):
    """입력조건: 설정 화면에서 본문 검색 선택 → 확인 없이 적용 → 확인+승인 참조 입력 후 적용 → 색인 재생성 → 본문 검색
    예상결과: 확인 없으면 오류, 적용 시 기존 색인 삭제 안내, 재색인 후 본문과 표/행 위치로 검색됨"""
    at, win, _ = real_app
    register(at, "계리평가팀", UNC_ROOT)
    click(at, key="setup_test_all")
    click(at, key="setup_run_index")
    at.radio(key="setup_mode_choice").set_value("full_text").run()
    assert any("정보보안 승인" in w.value for w in at.warning)
    click(at, key="setup_apply_mode")
    assert any("승인 확인과 승인 참조" in e.value for e in at.error)
    at.checkbox(key="setup_ack").set_value(True)
    at.text_input(key="setup_approver").set_value("SEC-2026-001").run()
    click(at, key="setup_apply_mode")
    assert any("기존 색인을 삭제" in s.value for s in at.success)
    assert "현재: **본문 검색**" in md(at) and "SEC-2026-001" in md(at)
    click(at, key="setup_test_all")
    click(at, key="setup_run_index")
    assert len(win.fs.reads) > 5
    at.radio(key="page").set_value("search").run()
    assert "메타데이터 전용 모드" not in md(at)
    at.text_input(key="query_text").set_value("허용 오차 롤포워드 대사")
    next(b for b in at.button if b.label == "검색").click().run()
    resp = at.session_state["last"]["resp"]
    assert resp.results and any(p.loc == "표 1 · 행 2" for p in resp.results[0].passages)
    rec("승인 기록 후 본문 색인, 표 행 위치로 검색")


def test_permission_revocation_visible_in_ui_without_resync(real_app):
    """입력조건: 본문 색인 후 한 문서의 권한 회수 → 같은 검색 재실행(색인 갱신 없음) → 미리보기 열기
    예상결과: 결과에서 즉시 사라지고 미리보기는 열 수 없음 안내"""
    at, win, _ = real_app
    register(at, "계리평가팀", UNC_ROOT)
    click(at, key="setup_test_all")
    at.radio(key="setup_mode_choice").set_value("full_text").run()
    at.checkbox(key="setup_ack").set_value(True)
    at.text_input(key="setup_approver").set_value("SEC-1").run()
    click(at, key="setup_apply_mode")
    click(at, key="setup_test_all")
    click(at, key="setup_run_index")
    at.radio(key="page").set_value("search").run()
    at.text_input(key="query_text").set_value("허용 오차 롤포워드 대사")
    next(b for b in at.button if b.label == "검색").click().run()
    first = at.session_state["last"]["resp"].results[0]
    assert first.file_name.endswith("v2.1.docx")
    win.fs.deny_read(win.unc("docx"))
    next(b for b in at.button if b.label == "검색").click().run()
    assert all(r.doc_id != first.doc_id for r in at.session_state["last"]["resp"].results)
    assert first.file_name not in md(at).replace("&#92;", "\\") or "IFRS17 결산 검증 가이드_v2.1.docx" not in md(at)


def test_delete_index_button(real_app):
    """입력조건: 색인 생성 후 설정 화면에서 확인 체크 후 '색인 삭제'
    예상결과: 확인 전에는 비활성, 확인 후 로컬 색인이 모두 삭제되고 단계 표시가 초기화"""
    at, win, _ = real_app
    register(at, "계리평가팀", UNC_ROOT)
    click(at, key="setup_test_all")
    click(at, key="setup_run_index")
    assert at.button(key="setup_delete_index").disabled
    at.checkbox(key="setup_del_confirm").set_value(True).run()
    click(at, key="setup_delete_index")
    assert any("삭제했습니다" in s.value for s in at.success) and "⬜ 색인 생성" in md(at)


def test_unregister_share_and_disable(real_app):
    """입력조건: 등록된 공유를 '색인에 사용' 해제 / 등록 해제
    예상결과: 사용 안 함이면 테스트·색인 대상에서 빠지고, 등록 해제하면 목록에서 사라짐"""
    at, win, _ = real_app
    register(at, "계리평가팀", UNC_ROOT)
    at.checkbox(key="setup_en_0").set_value(False).run()
    assert at.button(key="setup_test_all").disabled
    click(at, key="setup_unreg_0")
    assert any("등록 해제" in s.value or "등록을 해제" in s.value for s in at.success)
    assert "등록된 공유폴더가 없습니다" in " ".join(i.value for i in at.info)


def test_first_screen_hides_revoked_file_without_resync(real_app, rec):
    """입력조건: 본문 색인 후 한 파일의 권한 회수·다른 파일 삭제(색인 갱신 없음) → 앱 첫 화면(검색 전)
    예상결과: 문서 목록·경로·접근 가능 문서 수·유형별 건수·필터 선택지에 회수/삭제 파일이 나타나지 않음"""
    at, win, _ = real_app
    _ready_metadata(at)
    before = int(next(m for m in at.metric if m.label == "접근 가능한 통합 문서 수").value)
    assert "IFRS17 결산 검증 가이드_v2.1.docx" in md(at)
    docx_label = next(o for o in at.multiselect(key="f_types").options if o.startswith("Word") or "DOCX" in o.upper() or "워드" in o)
    win.fs.deny_read(win.unc("docx"))
    win.path("csv").unlink()
    at.run()
    assert not at.exception
    page = md(at).replace("&#92;", "\\")
    assert "IFRS17 결산 검증 가이드_v2.1.docx" not in page and "GoC_변동_2026-09.csv" not in page
    assert int(next(m for m in at.metric if m.label == "접근 가능한 통합 문서 수").value) == before - 2
    opts = at.multiselect(key="f_types").options
    assert next(o for o in opts if o.split(" (")[0] == docx_label.split(" (")[0]) != docx_label  # 건수가 줄어든 새 라벨
    rec(f"접근 가능 문서 {before} → {before - 2}, 회수·삭제 파일명 비노출")
