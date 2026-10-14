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
_RECORDS: list[dict] = []
_ACTUAL: dict[str, str] = {}


def pytest_addoption(parser):
    parser.addoption("--report-md", action="store", default=None, help="테스트 결과표 마크다운 저장 경로")


@pytest.fixture
def rec(request):
    """실제 결과를 기록한다: rec('검색 결과 GW-001, BS-001')"""
    def _rec(text: str) -> None:
        _ACTUAL[request.node.nodeid] = text
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
            actual = "실패: " + (str(call.excinfo.value).splitlines()[0][:150] if call.excinfo else "setup 오류")
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
