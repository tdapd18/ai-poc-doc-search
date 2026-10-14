"""실제 브라우저(Chromium) 종단 테스트: 앱 서버를 띄우고 검색·필터·선택·강조·경로 복사를 사람이 하듯 조작한다.

playwright 와 Chromium 이 없으면 건너뛴다 (pip install -r requirements-dev.txt).
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
PROJECT = Path(__file__).resolve().parent.parent
PDF_UNC = "\\\\fs-actu01.example.invalid\\계리평가\\결산검증\\결산_내부통제_점검보고서.pdf"
PPT_UNC = "\\\\fs-actu01.example.invalid\\계리평가\\교육자료\\월말결산_킥오프_자료.pptx"


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("browser")
    shutil.copytree(PROJECT / "data", tmp / "data")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "DATA_DIR": str(tmp / "data"), "INDEX_DB_PATH": str(tmp / "idx.db"), "LLM_PROVIDER": "none"}
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(port),
                             "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                            cwd=PROJECT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if urllib.request.urlopen(url + "/_stcore/health", timeout=1).status == 200:
                break
        except OSError:
            time.sleep(0.5)
    else:
        proc.terminate()
        pytest.skip("Streamlit 서버를 시작하지 못했습니다")
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def page(server):
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            exe = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium")
            try:
                browser = p.chromium.launch(executable_path=exe)
            except Exception:
                pytest.skip("Chromium 을 실행할 수 없습니다")
        ctx = browser.new_context(viewport={"width": 1800, "height": 1200},
                                  permissions=["clipboard-read", "clipboard-write"])
        pg = ctx.new_page()
        pg.goto(server)
        pg.wait_for_selector("text=검색 범위 및 필터", timeout=30000)
        pg.wait_for_timeout(800)
        yield pg
        browser.close()


def search(pg, query):
    pg.get_by_label("검색어 또는 질문").fill(query)
    pg.get_by_role("button", name="검색", exact=True).click()
    pg.wait_for_selector("text=검색 결과", timeout=15000)
    pg.wait_for_timeout(600)


def copy_first_code_block(pg):
    block = pg.locator('[data-testid="stCode"]').first
    block.hover()
    pg.wait_for_timeout(500)  # 복사 아이콘은 마우스를 올려야 나타난다
    block.locator("button").first.click()
    pg.wait_for_timeout(800)
    return pg.evaluate("navigator.clipboard.readText()")


def test_search_highlight_and_copy_unc_path(page, rec):
    """입력조건: 브라우저에서 '내부통제 점검 보고서 E101' 검색 → 1위 PDF 결과의 미리보기에서 경로 복사 버튼 클릭
    예상결과: 결과와 미리보기에 일치 단어 강조(mark)가 있고, 클립보드에 원본 UNC 경로가 정확히 복사됨"""
    search(page, "내부통제 점검 보고서 E101")
    assert page.locator("mark").count() >= 3
    assert page.locator("text=p.2").count() >= 1
    assert page.locator('[data-testid="stCode"]').first.inner_text().strip() == PDF_UNC
    # 결과 행에 '렌더된' UNC 경로가 역슬래시 2개로 시작해야 한다 (마크다운 이스케이프로 \\ 가 \ 로 줄어드는 결함 방지)
    assert page.inner_text("body").count(PDF_UNC) >= 2
    copied = copy_first_code_block(page)
    rec(f"클립보드: {copied}")
    assert copied == PDF_UNC


def test_filter_select_and_copy_other_result(page, rec):
    """입력조건: 'E101 오류 조치' 검색 후 문서 유형 필터에서 PowerPoint 선택, PPT 결과의 '위치 열기' 클릭 후 경로 복사
    예상결과: 결과가 PPTX 만 남고(슬라이드 3 위치), 미리보기가 PPT 문서로 바뀌며 클립보드에 PPT 의 UNC 경로가 복사됨"""
    search(page, "E101 오류 조치")
    before = page.locator('[data-testid="stBaseButton-secondary"]:has-text("위치 열기")').count()
    page.get_by_text("문서 유형 (비워두면 전체)").locator("xpath=ancestor::div[@data-testid='stMultiSelect']").click()
    page.get_by_role("option", name="PowerPoint (1)").click()
    page.keyboard.press("Escape")
    page.wait_for_timeout(1500)
    body = page.inner_text("body")
    assert "PPTX" in body and "슬라이드 3" in body and "결산_내부통제_점검보고서.pdf" not in body.split("관련 원문 미리보기")[0]
    page.locator('button:has-text("위치 열기")').first.click()
    page.wait_for_timeout(1200)
    assert page.locator('[data-testid="stCode"]').first.inner_text().strip() == PPT_UNC
    copied = copy_first_code_block(page)
    rec(f"위치 열기 버튼 {before}개 → 필터 후 PPT만, 복사: {copied}")
    assert copied == PPT_UNC


def test_user_switch_hides_unauthorized_in_browser(page):
    """입력조건: 브라우저에서 사용자를 재무팀으로 전환해 계리 전용 Excel/FAQ 가 걸리는 검색
    예상결과: 화면 어디에도 비인가 문서 제목이 나타나지 않음"""
    page.get_by_label("가상 사용자 선택").click()
    page.get_by_role("option", name="최재무 (재무팀)").click()
    page.wait_for_timeout(1200)
    search(page, "모델별 검증결과 집계 E101 RAFM 오류")
    body = page.inner_text("body")
    assert "모델별_검증결과" not in body and "RAFM 모델 실행 오류 대응 FAQ" not in body
