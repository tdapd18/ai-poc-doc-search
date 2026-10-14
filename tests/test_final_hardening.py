"""실무 전환 전 최종 보안 보완 — 건수 비누출, 세션 재검증, 로컬 색인 저장 위치 검증, 삭제/복구 안전성.
합성 Windows 공유(+가짜 ACL 판독기)만 사용한다. 실제 Windows 의 icacls/NTFS 동작은 Linux 에서 검증할 수 없다."""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from winshare import PHRASE, UNC_ROOT  # noqa: E402

from core.app_config import ConfigError
from core.indexer import IndexResetError, Indexer
from core.services import (StorageBlockedError, apply_index_mode, build_real_services, perform_index_reset,
                           sync_with_audit)
from core.storage_security import StorageStatus, check_storage, parse_sddl_broad_access, read_sddl_icacls
from test_real_mode import ready  # noqa: E402

SAFE = "O:S-1-5-21-1-2-3-1001G:DUD:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;S-1-5-21-1-2-3-1001)"
BROAD = SAFE + "(A;OICI;0x1200a9;;;BU)"
Q_MANY = "결산"


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
            h.update(str(p.stat().st_mtime_ns).encode())
    return h.hexdigest()


# ============================================================ P0-1 검색 총건수 비누출
def test_real_mode_counts_never_include_unverified_documents(make_real, win, rec):
    """입력조건: 여러 문서가 일치하는 질의를 top_k=1 로 검색, 일치 문서 일부의 권한 회수·삭제·네트워크 단절(색인 갱신 없음)
    예상결과: total_matched 는 항상 권한 확인이 끝난 표시 결과 수(전체 일치 수 아님), metadata_only_count 도 표시 결과 안에서만 계산, counts_exact=False"""
    svc, user, _ = ready(make_real, win)  # 메타데이터 전용 → 본문 미색인 문서 다수
    r1 = svc.engine.search(user, Q_MANY, top_k=1)
    assert r1.status == "ok" and r1.counts_exact is False
    assert r1.total_matched == len(r1.results) == 1  # 숨은 일치 문서 수가 드러나지 않음
    big = svc.engine.search(user, Q_MANY, top_k=20)
    assert big.total_matched == len(big.results) and big.metadata_only_count <= len(big.results)
    revoked = big.results[0]
    win.fs.deny_read(revoked.location)
    after = svc.engine.search(user, Q_MANY, top_k=20)
    assert revoked.doc_id not in {r.doc_id for r in after.results}
    assert after.total_matched == len(after.results) and after.counts_exact is False
    win.path("csv").unlink()
    win.fs.offline(UNC_ROOT)
    off = svc.engine.search(user, Q_MANY, top_k=20)
    assert off.total_matched == 0 and off.metadata_only_count == 0 and off.results == []
    win.fs.offline(UNC_ROOT, False)
    back = svc.engine.search(user, Q_MANY, top_k=20)
    assert back.total_matched == len(back.results) > 0
    rec(f"top_k=1 → total_matched={r1.total_matched}, 회수 후 {len(after.results)}건, 단절 0건, 복구 {len(back.results)}건")


def test_demo_mode_counts_still_exact(svc, users):
    """입력조건: 데모(가상 사용자) 모드 검색
    예상결과: 기존대로 전체 일치 건수를 표시(counts_exact=True, total_matched >= 표시 결과 수)"""
    r = svc.engine.search(users["actuary"], "결산", top_k=1)
    assert r.counts_exact is True and r.total_matched >= len(r.results)


# ============================================================ P0-2 세션 재검증 (엔진 + 화면)
def test_revalidate_response_rules(make_real, win):
    """입력조건: 검색 응답 → 권한 회수 / 복구 / 수정 / 장애 중 거부가 있었던 응답
    예상결과: 회수·수정 시 False, 복구 후 재검색한 응답은 True, 일시 거부(volatile)가 있던 응답은 항상 False"""
    svc, user, _ = ready(make_real, win, full=True)
    q = "결산 검증 허용 오차 롤포워드"
    resp = svc.engine.search(user, q)
    assert svc.engine.revalidate_response(user, resp)
    win.fs.deny_read(win.unc("docx"))
    assert not svc.engine.revalidate_response(user, resp)
    vol = svc.engine.search(user, q)
    assert vol.volatile and not svc.engine.revalidate_response(user, vol)
    win.fs.allow(win.unc("docx"))
    again = svc.engine.search(user, q)
    assert not again.volatile and svc.engine.revalidate_response(user, again)


@pytest.fixture
def full_app(win, tmp_path, monkeypatch):
    pytest.importorskip("streamlit.testing.v1")
    from test_real_app import click, md, register  # noqa: F401
    monkeypatch.setenv("APP_MODE", "real")
    monkeypatch.setenv("APP_HOME", str(tmp_path / "apphome"))
    monkeypatch.setenv("USERDOMAIN", "CORP")
    monkeypatch.setenv("USERNAME", "tester")
    monkeypatch.setattr("core.services.LocalFS", lambda *a, **k: win.fs)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)
    import streamlit
    from streamlit.testing.v1 import AppTest
    streamlit.cache_resource.clear()
    at = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=90).run()
    register(at, "계리평가팀", UNC_ROOT)
    click(at, key="setup_test_all")
    at.radio(key="setup_mode_choice").set_value("full_text").run()
    at.checkbox(key="setup_ack").set_value(True)
    at.text_input(key="setup_approver").set_value("SEC-1").run()
    click(at, key="setup_apply_mode")
    click(at, key="setup_test_all")
    click(at, key="setup_run_index")
    at.radio(key="page").set_value("search").run()
    assert not at.exception
    return at, win


def _search(at, q):
    at.text_input(key="query_text").set_value(q)
    next(b for b in at.button if b.label == "검색").click().run()
    assert not at.exception, [e.value for e in at.exception]


def _page(at):
    from test_real_app import md
    return md(at).replace("&#92;", "\\") + " ".join(i.value for i in at.info) + " ".join(c.value for c in at.caption)


def test_rendered_session_result_is_revalidated_on_every_run(full_app, rec):
    """입력조건: 검색 후 (재검색 버튼 없이) 권한 회수 → 화면 재실행 → 선택된 미리보기·이전 검색 이력 확인 → 권한 복구 → 재실행
    예상결과: 회수 직후 화면에서 파일명·UNC 경로·본문 문단·미리보기가 사라지고 재확인 안내 표시, 복구하면 다시 검색 결과에 나타남"""
    at, win = full_app
    _search(at, "허용 오차 롤포워드 대사")
    page = _page(at)
    name, path = "IFRS17 결산 검증 가이드_v2.1.docx", win.unc("docx")
    assert name in page and path in page and PHRASE not in page
    btn = next(b for b in at.button if b.key and b.key.startswith("loc_"))
    btn.click().run()
    assert at.session_state["selected"] is not None and name in _page(at)
    win.fs.deny_read(path)
    at.run()  # 재검색 없이 재렌더링
    assert not at.exception
    page = _page(at)
    assert name not in page and path not in page and "롤포워드" not in " ".join(m.value for m in at.markdown if "hit" in m.value)
    assert any("다시 확인" in i.value for i in at.info)
    assert all(r.location != path for r in at.session_state["last"]["resp"].results)
    sel = at.session_state["selected"]  # 선택돼 있던 미리보기도 닫히거나 '열 수 없음'으로 차단
    assert sel is None or any("열 수 없습니다" in w.value for w in at.warning)
    win.fs.allow(path)
    at.run()
    assert name in _page(at) and any(r.location == path for r in at.session_state["last"]["resp"].results)
    rec("회수 후 재렌더링: 파일명·경로·미리보기 비노출, 복구 후 재표시")


def test_rendered_session_result_hides_old_text_after_modification(full_app):
    """입력조건: 검색 후 원본 파일 수정(재검색·색인 갱신 없음) → 화면 재실행
    예상결과: 과거 본문 문단이 화면에 남지 않고 '원본 변경됨'만 표시"""
    from helpers import make_docx
    at, win = full_app
    _search(at, "허용 오차 롤포워드 대사")
    old_para = "모델 실행 결과를 확인한다"
    next(b for b in at.button if b.key and b.key.startswith("loc_")).click().run()
    assert old_para in " ".join(m.value for m in at.markdown) or "롤포워드" in _page(at)
    make_docx(win.path("docx"), [("p", "새로 바뀐 본문입니다 허용 오차 기준이 달라졌습니다.")], title="IFRS17 결산 검증 가이드")
    win.touch("docx", "2026-10-14")
    at.run()
    assert not at.exception
    blob = " ".join(m.value for m in at.markdown) + " ".join(w.value for w in at.warning) + " ".join(c.value for c in at.caption)
    assert old_para not in blob and "입력 데이터 대사를 먼저 수행한다" not in blob
    assert "원본 변경됨" in blob or "변경되어 과거 본문" in blob


def test_search_page_shows_no_total_count_wording(full_app):
    """입력조건: 실제 모드에서 검색 결과가 top_k 보다 많이 일치
    예상결과: '검색 결과 N건', '상위 N건 표시' 같은 전체 건수 암시 표현 없이 '접근 확인된 … 표시'만 안내"""
    at, win = full_app
    at.selectbox(key="top_k").set_value(5).run()
    _search(at, Q_MANY)
    text = " ".join(m.value for m in at.markdown)
    assert "접근 확인된 검색 결과" in text and "상위" not in text.split("접근 확인된 검색 결과", 1)[1][:120]
    assert "검색 결과 " not in text.replace("접근 확인된 검색 결과", "")
    assert "총 " not in text.split("접근 확인된 검색 결과", 1)[1][:80]


# ============================================================ P0-3 로컬 색인 저장 위치 검증
def test_sddl_parser_flags_only_broad_allow_aces():
    """입력조건: SYSTEM/관리자/본인만 / Users 허용 / Everyone 거부 / 도메인 사용자 허용 SDDL
    예상결과: 넓은 범위 주체의 허용 ACE 만 검출(SYSTEM·관리자·본인·거부 ACE 는 정상)"""
    assert parse_sddl_broad_access(SAFE) == []
    assert parse_sddl_broad_access(BROAD) == ["BU"]
    assert parse_sddl_broad_access("D:(D;;FA;;;WD)(A;;FA;;;SY)") == []
    assert parse_sddl_broad_access("D:(A;;FA;;;WD)") == ["WD"]
    assert parse_sddl_broad_access("D:(A;;FR;;;S-1-5-21-5-6-7-513)") == ["S-1-5-21-5-6-7-513"]
    assert parse_sddl_broad_access("D:(A;;FR;;;AU)") == ["AU"]


def test_windows_acl_verification_blocks_unsafe_or_unverifiable(tmp_path, rec):
    """입력조건: (가짜 ACL 판독기) 안전한 ACL / icacls 는 성공했으나 Users 허용 ACL / 판독 실패(None) / 판독기 예외
    예상결과: 안전할 때만 색인 허용. 넓은 접근·확인 불가·예외는 모두 색인과 본문 차단(명령 성공만으로 안전 판단하지 않음)"""
    home = tmp_path / "h"
    ok = check_storage(home, platform="win32", acl_reader=lambda p: SAFE, env={})
    assert ok.allow_index and ok.allow_body and ok.verified and ok.private and not ok.messages
    broad = check_storage(home, platform="win32", acl_reader=lambda p: BROAD, env={})
    assert not broad.allow_index and not broad.allow_body and "acl_broad_access" in broad.reasons
    none = check_storage(home, platform="win32", acl_reader=lambda p: None, env={})
    assert not none.allow_index and "acl_unverifiable" in none.reasons and not none.verified

    def boom(p):
        raise RuntimeError("x")
    exc = check_storage(home, platform="win32", acl_reader=boom, env={})
    assert not exc.allow_index and not exc.allow_full_text
    for st in (broad, none, exc):  # 안내문에 경로·계정 같은 내부 정보 없음
        assert all(str(tmp_path) not in m for m in st.messages) and st.messages
    rec("안전=허용, 넓은 접근·판독 실패·예외=차단")


def test_existing_db_file_acl_is_also_checked(tmp_path):
    """입력조건: 폴더 ACL 은 안전하지만 기존 index.db 파일에 Users 허용 ACE
    예상결과: 색인 차단"""
    home = tmp_path / "h"
    home.mkdir()
    (home / "index.db").write_bytes(b"")
    st = check_storage(home, platform="win32", acl_reader=lambda p: BROAD if p.name == "index.db" else SAFE, env={})
    assert not st.allow_index


def test_icacls_reader_is_read_only_and_parses_utf16(monkeypatch, tmp_path):
    """입력조건: read_sddl_icacls 호출(icacls 대체 실행기)
    예상결과: 명령은 '/save' 만 사용(/grant·/deny·/inheritance·/remove 없음 → SYSTEM·관리자 권한을 건드리지 않음), UTF-16 출력에서 SDDL 추출"""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        out = Path(cmd[cmd.index("/save") + 1])
        out.write_bytes(("\r\n" + str(tmp_path) + "\r\n" + SAFE + "\r\n").encode("utf-16"))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr("core.storage_security.subprocess.run", fake_run)
    assert read_sddl_icacls(tmp_path) == SAFE
    flat = " ".join(calls[0]).lower()
    assert "/save" in flat and not any(x in flat for x in ("/grant", "/deny", "/inheritance", "/remove", "/setowner", "/reset"))
    monkeypatch.setattr("core.storage_security.subprocess.run", lambda *a, **k: subprocess.CompletedProcess(a, 5, "", "denied"))
    assert read_sddl_icacls(tmp_path) is None


def test_cloud_sync_folder_blocks_body_not_metadata(tmp_path):
    """입력조건: 색인 폴더가 OneDrive 아래(경로명 / OneDrive 환경변수 하위)
    예상결과: cloud_sync=True, 본문 표시·본문 모드 차단, 안내문 제공 (메타데이터 색인은 가능)"""
    p = tmp_path / "OneDrive - 회사" / "app"
    st = check_storage(p, env={})
    assert st.cloud_sync and not st.allow_body and not st.allow_full_text and st.allow_index
    root = tmp_path / "SyncRoot"
    st2 = check_storage(root / "a", env={"OneDrive": str(root)})
    assert st2.cloud_sync and not st2.allow_body
    assert not check_storage(tmp_path / "plain", env={"OneDrive": str(root)}).cloud_sync


@pytest.mark.skipif(os.name != "posix", reason="POSIX 권한 비트")
def test_posix_loose_dir_is_tightened_for_own_folder(tmp_path):
    """입력조건: (리눅스) 앱이 쓰는 개인 폴더가 0755
    예상결과: 소유자 전용으로 맞추고 통과 (Windows 는 권한을 바꾸지 않고 검증만 한다)"""
    d = tmp_path / "h"
    d.mkdir()
    d.chmod(0o755)
    assert check_storage(d).allow_index and (d.stat().st_mode & 0o077) == 0


def test_blocked_storage_prevents_index_creation(make_real, win, monkeypatch, tmp_path, rec):
    """입력조건: 폴더 권한 검증 실패 상태에서 색인 생성 시도(sync_with_audit) 및 본문 모드 전환
    예상결과: StorageBlockedError, 색인 0건(공유 파일을 읽지도 않음), 본문 모드 전환 거부, 원본 파일 불변"""
    blocked = StorageStatus(False, True, False, True, ("acl_unverifiable",), ("권한을 확인하지 못했습니다.",))
    monkeypatch.setattr("core.services.check_storage", lambda home: blocked)
    before = tree_digest(win.local)
    svc = make_real()
    assert not svc.storage.allow_index
    with pytest.raises(StorageBlockedError):
        sync_with_audit(svc)
    assert svc.indexer.count_documents() == 0
    with pytest.raises(ConfigError):
        apply_index_mode(svc, "full_text", approver="SEC", acknowledged=True)
    assert tree_digest(win.local) == before
    rec("차단: 색인 0건, 본문 모드 거부, 원본 불변")


def test_existing_index_with_unverified_storage_hides_body(make_real, win, monkeypatch, tmp_path, rec):
    """입력조건: 본문 색인이 이미 있는데 다음 실행에서 저장 위치 보호를 확인하지 못함
    예상결과: 본문 문구 검색 결과 없음·미리보기 본문 없음·문단 비노출(파일명 검색은 가능), 본문 모드 런타임 해제, 설정 파일은 변경 없음"""
    svc, user, _ = ready(make_real, win, full=True)
    home = svc.indexer.db_path.parent
    q = "결산 검증 허용 오차 롤포워드"
    assert svc.engine.search(user, q).results[0].passages
    blocked = StorageStatus(False, True, False, True, ("acl_unverifiable",), ("확인 불가",))
    monkeypatch.setattr("core.services.check_storage", lambda h: blocked)
    cfg_before = (home / "config.json").read_bytes()
    svc2 = build_real_services(home, fs=win.fs, identity=svc.identity)
    u2 = svc2.access.current_user()
    assert svc2.engine.body_blocked and not svc2.config.full_text
    r = svc2.engine.search(u2, q)
    assert all(not x.passages for x in r.results)
    assert svc2.engine.search(u2, PHRASE).status == "no_results"
    assert svc2.engine.search(u2, "검증 가이드", scope="body").results == []
    assert svc2.engine.search(u2, "IFRS17 결산 검증 가이드").results  # 파일명 검색은 유지
    doc_id = svc2.engine.list_visible_documents(u2)[0].doc_id
    assert svc2.engine.open_document(u2, doc_id)[1] == [] and svc2.engine.matching_chunks(u2, doc_id, q) == []
    assert (home / "config.json").read_bytes() == cfg_before
    rec("보호 미확인: 본문·문단·미리보기 차단, 파일명 검색 유지")


def test_cloud_sync_home_blocks_full_text_but_allows_metadata(make_real, win, tmp_path):
    """입력조건: APP_HOME 이 OneDrive 폴더 아래
    예상결과: 본문 색인 모드 전환 거부(ConfigError), 메타데이터 색인은 가능하고 본문은 표시되지 않음"""
    svc = make_real(home=tmp_path / "OneDrive - Corp" / "h")
    assert svc.storage.cloud_sync
    with pytest.raises(ConfigError, match="안전하지"):
        apply_index_mode(svc, "full_text", approver="SEC", acknowledged=True)
    sync_with_audit(svc)
    assert svc.indexer.count_documents() > 0 and svc.engine.body_blocked


# ============================================================ 색인 삭제·복구·모드 변경
def test_corrupt_index_keeps_originals_and_rebuilds_without_reexposing(make_real, win, rec):
    """입력조건: 본문 색인 후 index.db 손상 → 다시 시작 → 그 사이 한 파일 권한 회수 → 재색인
    예상결과: 원본 공유 파일은 바이트·수정시각 불변, 복구 알림 표시, 이전 본문 문구가 새 DB 에 없음, 회수된 문서는 재색인·검색·목록에 나타나지 않음"""
    svc, user, _ = ready(make_real, win, full=True)
    home = svc.indexer.db_path.parent
    before = tree_digest(win.local)
    svc.indexer.db_path.write_bytes(b"garbage" * 500)
    win.fs.deny_read(win.unc("docx"))
    svc2 = build_real_services(home, fs=win.fs, identity=svc.identity)
    assert svc2.indexer.recovered and any("손상" in n for n in svc2.notices) and svc2.indexer.count_documents() == 0
    assert PHRASE.encode() not in svc2.indexer.db_path.read_bytes()
    assert svc2.config.full_text  # 설정(승인 기록)은 유지, 색인만 다시 생성
    sync_with_audit(svc2)
    u2 = svc2.access.current_user()
    assert not any(d.location == win.unc("docx") for d in svc2.engine.list_visible_documents(u2))
    assert svc2.engine.search(u2, PHRASE).results == []
    assert tree_digest(win.local) == before
    rec("원본 불변, 손상 복구 알림, 권한 회수 문서 재노출 없음")


def test_undeletable_corrupt_index_blocks_instead_of_crashing(make_real, win, monkeypatch):
    """입력조건: 손상된 index.db 를 삭제할 수 없음
    예상결과: 앱은 중단되지 않고 임시 메모리 색인으로 시작하며 색인 생성·본문 표시 차단과 안내 제공"""
    svc, *_ = ready(make_real, win, full=True)
    home = svc.indexer.db_path.parent
    svc.indexer.db_path.write_bytes(b"x" * 3000)
    monkeypatch.setattr("core.storage_security.wipe_file", lambda p: False)
    svc2 = build_real_services(home, fs=win.fs, identity=svc.identity)
    assert not svc2.storage.allow_index and svc2.engine.body_blocked and "index_unrecoverable" in svc2.storage.reasons
    with pytest.raises(StorageBlockedError):
        sync_with_audit(svc2)


def test_reset_failure_is_reported_and_blocks_body_until_retry(make_real, win, monkeypatch, rec):
    """입력조건: 색인 수준 변경 중 색인 삭제(VACUUM) 실패 → 재시도
    예상결과: IndexResetError 로 사용자에게 알리고 그 사이 본문 표시 차단, 재시작해도 삭제 마무리(reset.pending), 성공 후 DB 에 본문 없음"""
    svc, user, _ = ready(make_real, win, full=True)
    home = svc.indexer.db_path.parent
    real_vacuum = Indexer.vacuum
    monkeypatch.setattr(Indexer, "vacuum", lambda self: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(IndexResetError):
        apply_index_mode(svc, "metadata_only")
    assert svc.engine.body_blocked and (home / "reset.pending").exists() and not svc.storage.allow_index
    r = svc.engine.search(user, "결산 검증 허용 오차 롤포워드")
    assert all(not x.passages for x in r.results)
    monkeypatch.setattr(Indexer, "vacuum", real_vacuum)
    svc2 = build_real_services(home, fs=win.fs, identity=svc.identity)  # 재시작: 미완료 삭제 마무리
    assert svc2.indexer.count_documents() == 0 and not (home / "reset.pending").exists() and svc2.storage.allow_index
    assert PHRASE.encode() not in svc2.indexer.db_path.read_bytes() and not svc2.engine.body_blocked
    perform_index_reset(svc2)  # 재시도 가능
    rec("삭제 실패 알림·본문 차단, 재시작 시 마무리, 본문 문구 제거")


def test_mode_change_removes_old_body_and_cache(make_real, win):
    """입력조건: 본문 검색 결과를 캐시한 뒤 메타데이터 전용으로 변경
    예상결과: 이전 본문은 검색되지 않고 캐시 응답도 재사용되지 않으며 DB 바이트에도 남지 않음"""
    svc, user, _ = ready(make_real, win, full=True)
    q = "결산 검증 허용 오차 롤포워드"
    assert svc.engine.search(user, q).results and svc.engine.search(user, q).from_cache
    assert apply_index_mode(svc, "metadata_only")
    after = svc.engine.search(user, q)
    assert not after.from_cache and after.results == [] and svc.indexer.count_documents() == 0
    assert PHRASE.encode() not in svc.indexer.db_path.read_bytes()
    sync_with_audit(svc)
    assert svc.engine.search(user, PHRASE).results == [] and all(not x.passages for x in svc.engine.search(user, q).results)


def test_sqlite_journal_setting_documented_risk_is_handled(make_real, win):
    """입력조건: 저널을 메모리에 두는 설정 + 비정상 종료로 중간에 잘린 DB
    예상결과: quick_check 에서 감지되어 폐기·재생성되고 앱이 계속 동작함 (원본 무관)"""
    svc, *_ = ready(make_real, win, full=True)
    p = svc.indexer.db_path
    data = p.read_bytes()
    p.write_bytes(data[: len(data) // 2])  # 잘린 파일
    svc2 = build_real_services(p.parent, fs=win.fs, identity=svc.identity)
    assert svc2.indexer.count_documents() in (0, svc.indexer.count_documents())
    assert svc2.storage.allow_index
