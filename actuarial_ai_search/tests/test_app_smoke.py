"""브라우저 없이 Streamlit 앱을 구동하는 스모크 테스트 (AppTest). 시각적 확인은 README_DEMO.md 의 수동 테스트 참조."""
import shutil
from pathlib import Path

import pytest

streamlit_testing = pytest.importorskip("streamlit.testing.v1")
PROJECT = Path(__file__).resolve().parent.parent


@pytest.fixture
def app(tmp_path, monkeypatch):
    data = tmp_path / "data"
    shutil.copytree(PROJECT / "data", data)
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.db"))
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.chdir(PROJECT)
    from streamlit.testing.v1 import AppTest
    import streamlit
    streamlit.cache_resource.clear()
    at = AppTest.from_file(str(PROJECT / "app.py"), default_timeout=60).run()
    assert not at.exception
    return at, data


def _click(at, prefix):
    next(b for b in at.button if b.label.startswith(prefix)).click().run()
    assert not at.exception


def test_app_starts_with_three_sources(app, rec):
    """입력조건: 웹앱 첫 실행
    예상결과: 예외 없이 기동, 자동 색인으로 계리평가팀 기준 9건 표시"""
    at, _ = app
    assert at.metric[0].value == "9"
    rec("앱 기동·자동 색인 확인")


def test_search_select_source_and_preview(app, rec):
    """입력조건: 추천 질문 클릭 → 근거 문서 보기 클릭
    예상결과: 검색 결과와 근거 문서가 표시되고, 오른쪽 패널에 문서명/버전/원본 위치가 나타남"""
    at, _ = app
    _click(at, "RAFM 모델 실행 오류가 나면")
    html = " ".join(m.value for m in at.markdown)
    assert "관련 근거 문서" in html and "RAFM 모델 실행 오류 대응 FAQ" in html
    _click(at, "[2] 근거 문서 보기")
    html = " ".join(m.value for m in at.markdown)
    assert "문서 버전" in html and "groupware.example.invalid" in html
    rec("검색→출처 선택→원문/원본 위치 표시 확인")


def test_empty_query_shows_warning(app):
    """입력조건: 검색어 없이 검색 버튼
    예상결과: 경고 안내, 앱 중단 없음"""
    at, _ = app
    next(b for b in at.button if b.label == "검색").click().run()
    assert not at.exception and any("검색어를 입력" in w.value for w in at.warning)


def test_user_switch_changes_visible_documents(app, rec):
    """입력조건: 가상 사용자를 재무팀으로 전환
    예상결과: 접근 가능 문서 수 9 → 3, 계리 전용 문서 제목이 목록에서 사라짐"""
    at, _ = app
    at.selectbox[0].select("u_finance").run()
    assert at.metric[0].value == "3"
    labels = [b.label for b in at.button]
    assert "RAFM 모델 실행 오류 대응 FAQ" not in labels and "IFRS17 결산 검증 가이드" in labels
    rec("재무팀 3건 표시")


def test_refresh_button_and_revocation_hides_old_answer(app, rec):
    """입력조건: 재무팀 검색 후 SF-001 권한 회수 → 색인 갱신 버튼
    예상결과: 갱신 후 결과·근거 패널에서 SF-001 내용이 사라지고, 이전 답변 이력은 숨김 안내가 표시됨"""
    at, data = app
    at.selectbox[0].select("u_finance").run()
    at.text_input[0].set_value("IFRS17 결산 검증 절차")
    next(b for b in at.button if b.label == "검색").click().run()
    assert any("IFRS17 결산 검증 가이드" in m.value for m in at.markdown)
    p = data / "shared_folder" / "결산검증" / "IFRS17_결산검증가이드.md"
    p.write_text(p.read_text(encoding="utf-8").replace("allowed_groups: [actuarial, finance]",
                                                       "allowed_groups: [actuarial]"), encoding="utf-8")
    _click(at, "🔄 색인 갱신")
    assert not any("IFRS17 결산 검증 가이드" in m.value for m in at.markdown)
    assert any("접근권한이 변경" in w.value for w in at.warning)  # 이전 답변 숨김 안내 (이력)
    assert not any("SF-001" in m.value for m in at.markdown)  # 근거 패널에도 회수된 문서 정보 없음
    rec("권한 회수 후 결과/원문/이력에서 SF-001 노출 없음")
