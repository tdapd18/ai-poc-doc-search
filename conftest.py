"""공통 픽스처 + 테스트 결과 기록(입력조건 / 예상 결과 / 실제 결과 / 통과 여부).

사용: pytest --report-md docs/TEST_RESULTS.md   (결과표를 마크다운으로 저장)
각 테스트 docstring 의 '입력조건:' '예상결과:' 줄과, 테스트가 rec(...) 로 남긴 실제 결과를 표로 만든다.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from core.services import build_services

PROJECT = Path(__file__).resolve().parent
# 가상 데이터 기준 사용자별 접근 가능 문서
FINANCE_DOCS = {"SF-001", "GW-002", "BS-002", "SF-101", "SF-103", "SF-201", "SF-202"}
ACTUARY_COUNT, FINANCE_COUNT, ADMIN_COUNT, TOTAL_DOCS = 13, 7, 15, 15
_RECORDS: list[dict] = []
_ACTUAL: dict[str, str] = {}


def pytest_addoption(parser):
    parser.addoption("--report-md", action="store", default=None, help="테스트 결과표 마크다운 저장 경로")


@pytest.fixture
def rec(request):
    """실제 결과를 기록한다: rec('검색 결과 GW-001, BS-001')"""
    def _rec(text: str) -> None:
        _ACTUAL[request.node.nodeid] = str(text)
    return _rec


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        doc = (item.function.__doc__ or "").strip()
        inp = re.search(r"입력조건:\s*(.+)", doc)
        exp = re.search(r"예상결과:\s*(.+)", doc)
        actual = _ACTUAL.get(item.nodeid, "")
        if report.outcome != "passed":
            lines = str(call.excinfo.value).splitlines() if call and call.excinfo else []
            actual = "실패: " + ((lines[0] if lines else repr(call.excinfo.value))[:150] if call and call.excinfo
                               else "setup 오류")
        elif not actual:
            actual = "예상 결과와 일치"
        _RECORDS.append({
            "file": Path(str(item.fspath)).name, "name": item.name, "input": inp.group(1) if inp else "-",
            "expected": exp.group(1) if exp else "-", "actual": actual,
            "passed": report.outcome == "passed",
        })


def pytest_sessionfinish(session, exitstatus):
    path = session.config.getoption("--report-md")
    if not path or not _RECORDS:
        return
    ok = sum(r["passed"] for r in _RECORDS)
    lines = [
        "# 자동 테스트 결과 (pytest)", "",
        f"- 전체 {len(_RECORDS)}건 중 통과 {ok}건 / 실패 {len(_RECORDS) - ok}건",
        "- 데이터는 모두 가상 더미데이터이며 외부 네트워크·실제 LLM 호출은 없습니다 (LLM 관련은 Mock 구현으로 검증).",
        "", "| 파일 | 테스트 | 입력조건 | 예상 결과 | 실제 결과 | 통과 |", "|---|---|---|---|---|---|",
    ]
    esc = lambda s: s.replace("|", "\\|").replace("\n", " ")
    for r in _RECORDS:
        lines.append(f"| {r['file']} | `{r['name']}` | {esc(r['input'])} | {esc(r['expected'])} | "
                     f"{esc(r['actual'])} | {'✅' if r['passed'] else '❌'} |")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def data_copy(tmp_path) -> Path:
    """가상 데이터를 임시 폴더로 복사 (테스트가 파일을 수정/삭제해도 원본은 안전)."""
    dst = tmp_path / "data"
    shutil.copytree(PROJECT / "data", dst)
    return dst


@pytest.fixture
def svc(data_copy, tmp_path):
    """색인이 만들어진 서비스 묶음."""
    s = build_services(data_copy, tmp_path / "index.db")
    s.sync.sync()
    return s


@pytest.fixture
def users(svc):
    return {
        "actuary": svc.access.get_user("u_actuary"),
        "finance": svc.access.get_user("u_finance"),
        "admin": svc.access.get_user("u_admin"),
    }


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Streamlit AppTest 로 구동한 앱 + 임시 데이터 폴더 (브라우저 없이 화면 동작을 검증)."""
    pytest.importorskip("streamlit.testing.v1")
    data = tmp_path / "data"
    shutil.copytree(PROJECT / "data", data)
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.db"))
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.chdir(PROJECT)
    import streamlit
    from streamlit.testing.v1 import AppTest
    streamlit.cache_resource.clear()
    at = AppTest.from_file(str(PROJECT / "app.py"), default_timeout=60).run()
    assert not at.exception
    return at, data


# ---------------------------------------------------------------- 실제 Windows 모드(합성 공유) 픽스처
@pytest.fixture
def win(tmp_path):
    import sys
    sys.path.insert(0, str(PROJECT / "tests"))
    from winshare import build_windows_share
    return build_windows_share(tmp_path)


@pytest.fixture
def make_real(tmp_path, win):
    """실제 모드 서비스 팩토리: make_real(identity=..., home=...) — 합성 공유를 등록한 상태."""
    import sys
    sys.path.insert(0, str(PROJECT / "tests"))
    from winshare import UNC_ROOT
    from core.identity import WindowsIdentity
    from core.services import build_real_services

    def _make(*, user="tester", domain="CORP", home=None, register=True, full_text=False, max_mb=None, **cfg):
        svc = build_real_services(home or tmp_path / "home", fs=win.fs, identity=WindowsIdentity(domain, user))
        if max_mb is not None:
            svc.config.max_file_mb = max_mb
        for k, v in cfg.items():
            setattr(svc.config, k, v)
        if register and not svc.shares.list():
            svc.shares.register_unc("계리평가팀", UNC_ROOT)
        if full_text:
            from core.services import apply_index_mode
            apply_index_mode(svc, "full_text", approver="SEC-TEST", acknowledged=True)
        return svc
    return _make
