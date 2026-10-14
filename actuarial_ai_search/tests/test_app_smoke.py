"""브라우저 없이 Streamlit 앱을 구동하는 스모크 테스트 (AppTest). 시각적 확인은 README_DEMO.md 의 수동 테스트 참조."""
import shutil
from pathlib import Path

import pytest

streamlit_testing = pytest.importorskip("streamlit.testing.v1")
PROJECT = Path(__file__).resolve().parent.parent


def _click(at, prefix):
    next(b for b in at.button if b.label.startswith(prefix)).click().run()
    assert not at.exception


def test_app_starts_with_three_sources(app, rec):
    """입력조건: 웹앱 첫 실행
    예상결과: 예외 없이 기동, 자동 색인으로 계리평가팀 기준 13건 표시"""
    at, _ = app
    assert at.metric[0].value == "13"
    rec("앱 기동·자동 색인 확인")


def test_search_select_source_and_preview(app, rec):
    """입력조건: 추천 질문 클릭 → 두 번째 결과의 '문서 미리보기' 클릭
    예상결과: 검색 결과가 표시되고, 오른쪽 패널에 선택한 문서의 문서명/버전/원본 위치가 나타남"""
    at, _ = app
    _click(at, "RAFM 모델 실행 오류가 나면")
    html = " ".join(m.value for m in at.markdown)
    assert "검색 결과 " in html and "RAFM 모델 실행 오류 대응 FAQ" in html
    second = [b for b in at.button if b.label == "문서 미리보기"][1]
    second.click().run()
    html = " ".join(m.value for m in at.markdown)
    assert "버전 / 최종 수정일" in html and "원본" in html
    assert at.session_state["selected"][0] == at.session_state["last"]["resp"].results[1].doc_id
    rec("검색→출처 선택→원문/원본 위치 표시 확인")


def test_empty_query_shows_warning(app):
    """입력조건: 검색어 없이 검색 버튼
    예상결과: 경고 안내, 앱 중단 없음"""
    at, _ = app
    next(b for b in at.button if b.label == "검색").click().run()
    assert not at.exception and any("검색어를 입력" in w.value for w in at.warning)


def test_user_switch_changes_visible_documents(app, rec):
    """입력조건: 가상 사용자를 재무팀으로 전환
    예상결과: 접근 가능 문서 수 13 → 7, 계리 전용 문서 제목이 문서 목록(첫 화면)에서 사라짐"""
    at, _ = app
    at.selectbox[0].select("u_finance").run()
    assert at.metric[0].value == "7"
    page = " ".join(m.value for m in at.markdown)
    assert "RAFM 모델 실행 오류 대응 FAQ" not in page and "IFRS17_결산검증가이드.md" in page
    assert "모델별_검증결과" not in page
    rec("재무팀 7건 표시")


def test_refresh_button_and_revocation_hides_old_answer(app, rec):
    """입력조건: 재무팀 검색 후 SF-001 권한 회수 → 색인 갱신 버튼
    예상결과: 갱신 후 결과·근거 패널에서 SF-001 내용이 사라지고, 이전 답변 이력은 숨김 안내가 표시됨"""
    at, data = app
    at.selectbox[0].select("u_finance").run()
    at.text_input[0].set_value("IFRS17 결산 검증 절차")
    next(b for b in at.button if b.label == "검색").click().run()
    assert any("IFRS17 결산 검증 가이드" in m.value for m in at.markdown)
    p = data / "shared_folder" / "계리평가" / "결산검증" / "IFRS17_결산검증가이드.md"
    p.write_text(p.read_text(encoding="utf-8").replace("allowed_groups: [actuarial, finance]",
                                                       "allowed_groups: [actuarial]"), encoding="utf-8")
    _click(at, "🔄 색인 갱신")
    assert not any("IFRS17 결산 검증 가이드" in m.value for m in at.markdown)
    assert any("접근권한이 변경" in w.value for w in at.warning)  # 이전 답변 숨김 안내 (이력)
    assert not any("SF-001" in m.value for m in at.markdown)  # 근거 패널에도 회수된 문서 정보 없음
    rec("권한 회수 후 결과/원문/이력에서 SF-001 노출 없음")
