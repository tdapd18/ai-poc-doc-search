"""연결 테스트·사전 점검(core/setup_check.py) — 합성 Windows 공유. 파일 내용을 읽지 않는다는 점을 함께 검증한다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from winshare import UNC_ROOT  # noqa: E402

from core.app_config import AppConfig
from core.setup_check import check_share
from core.shares import Share


def share(**kw):
    return Share("계리평가팀", kw.pop("unc", UNC_ROOT), kind="unc", **kw)


def test_successful_check_reports_stats_without_reading_content(win, rec):
    """입력조건: 정상 합성 공유에서 연결 테스트
    예상결과: 성공(ok), 형식별 파일 수·미지원·구형 집계, 권한 표본 읽기 가능, 파일 내용 읽기 호출 0회"""
    win.fs.deny_read(UNC_ROOT + "\\기밀")
    r = check_share(share(), win.fs, AppConfig())
    rec(f"ok={r.ok} 색인대상≈{r.indexable} 형식={r.by_ext} 표본 {r.readable}/{r.sampled}")
    assert r.ok and r.code == "ok" and r.stage == "done"
    assert r.by_ext["docx"] == 3 and r.by_ext["csv"] == 1 and r.by_ext["pdf"] == 1 and r.by_ext["xlsx"] == 2
    assert r.legacy == 2 and r.unsupported >= 1 and r.top_folders >= 5 and r.latency_ms >= 0
    assert r.sampled > 0 and r.readable + r.denied + r.transient == r.sampled
    assert win.fs.reads == [] and win.fs.opens  # 열기 가능 여부만 확인


def test_exclusions_applied_in_check(win):
    """입력조건: 기본 제외 패턴(~$, Thumbs.db, desktop.ini, 숨김)과 공유 단위 제외 패턴
    예상결과: 점검 통계에서도 제외 대상은 집계되지 않음"""
    base = check_share(share(), win.fs, AppConfig())
    narrowed = check_share(share(exclude=("구형", "결산")), win.fs, AppConfig())
    assert narrowed.indexable < base.indexable and narrowed.legacy == 0


def test_error_codes_with_guidance(win):
    """입력조건: 잘못된 경로 형식 / 계정 접근 거부 / 없는 경로 / 오프라인
    예상결과: invalid_path / denied / not_found / unavailable 로 구분되고 사용자용 메시지가 있음"""
    assert check_share(share(unc="C:\\temp"), win.fs, AppConfig()).code == "invalid_path"
    win.fs.deny_list(UNC_ROOT)
    r = check_share(share(), win.fs, AppConfig())
    assert (r.ok, r.code, r.stage) == (False, "denied", "connect") and "권한" in r.message
    win.fs.allow(UNC_ROOT)
    r = check_share(share(unc="\\\\fs-corp01.example.invalid\\계리평가팀\\없는폴더"), win.fs, AppConfig())
    assert r.code == "not_found" and "서버 이름" in r.message
    win.fs.offline(UNC_ROOT)
    r = check_share(share(), win.fs, AppConfig())
    assert r.code == "unavailable" and "VPN" in r.message


def test_denied_subfolders_and_sample_permission_warnings(win):
    """입력조건: 하위 폴더 목록 거부, 일부 파일 읽기 거부
    예상결과: 접근 불가 폴더 수·표본 거부가 경고로 보고되고 점검은 계속 성공"""
    win.fs.deny_list(UNC_ROOT + "\\목록거부")
    for sub in ("결산", "데이터", "모델", "A", "B"):
        win.fs.deny_read(UNC_ROOT + "\\" + sub)
    r = check_share(share(), win.fs, AppConfig(), sample_files=40)
    assert r.ok and r.denied_dirs == 1 and r.denied >= 1
    assert any("읽을 수 없습니다" in w for w in r.warnings) and any("하위 폴더" in w for w in r.warnings)


def test_scan_limit_and_time_budget_mark_truncated(win):
    """입력조건: 점검 항목 한도를 낮춤 / 시간 한도를 초과하는 시계
    예상결과: truncated=True 와 추정치 안내 경고"""
    r = check_share(share(), win.fs, AppConfig(), scan_limit=5)
    assert r.truncated and r.scanned_entries <= 6 and any("일부만 점검" in w for w in r.warnings)
    ticks = iter(range(0, 10_000, 5))
    r2 = check_share(share(), win.fs, AppConfig(), time_budget_s=8, clock=lambda: next(ticks))
    assert r2.truncated


def test_oversize_files_warned(win):
    """입력조건: 크기 한도(1MB)를 넘는 파일
    예상결과: 경고로 보고(파일명 검색만 가능)"""
    (win.local / "큰파일.csv").write_bytes(b"a,b\n" + b"x,y\n" * 400_000)
    cfg = AppConfig()
    cfg.max_file_mb = 1
    r = check_share(share(), win.fs, cfg)
    assert r.oversize == 1 and any("파일명 검색만" in w for w in r.warnings)
