"""실제 모드 보안 보완 — 표시 직전 재검증(목록·건수·필터), 복구/회수/삭제/변경 시나리오, 로컬 색인 저장 보안.
합성 Windows 공유만 사용한다(실제 회사 공유 미접속)."""
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from winshare import PHRASE, UNC_ROOT  # noqa: E402

from core.history import HistoryEntry, revalidate_history
from core.search_engine import location_key
from core.services import build_real_services, sync_with_audit
from core.storage_security import find_residue, purge_residue, storage_warnings, wipe_file
from test_real_mode import ready  # noqa: E402

Q = "결산 검증 허용 오차 롤포워드"


def names(docs):
    return {d.file_name for d in docs}


def facets(docs):
    """앱 첫 화면이 만드는 값: 건수, 유형별 건수, 위치(공유폴더)별 건수 + 필터 선택지."""
    return len(docs), Counter(d.file_type for d in docs), Counter(location_key(d) for d in docs)


# ============================================================ 1·2·3. 목록/건수/필터 재검증
def test_list_hides_revoked_file_everywhere_before_resync(make_real, win, rec):
    """입력조건: 색인 후 DOCX 읽기 권한 회수(색인 갱신 없음) — 문서 목록·접근 가능 문서 수·유형별/위치별 건수·필터 선택지·경로
    예상결과: 회수된 파일명·경로가 목록에 없고 건수가 1 줄며, 해당 유형 건수가 줄어들고 필터 선택지가 실제 접근 가능한 값만 남음"""
    svc, user, _ = ready(make_real, win, full=True)
    before = svc.engine.list_visible_documents(user)
    assert any(d.file_name.endswith("v2.1.docx") for d in before)
    n0, types0, locs0 = facets(before)
    win.fs.deny_read(win.unc("docx"))
    after = svc.engine.list_visible_documents(user)
    n1, types1, locs1 = facets(after)
    assert n1 == n0 - 1 and types1["docx"] == types0["docx"] - 1
    assert not any(d.file_name.endswith("v2.1.docx") or d.location == win.unc("docx") for d in after)
    assert svc.indexer.get_document(next(d.doc_id for d in before if d.location == win.unc("docx"))) is not None  # 색인에는 아직 남아 있음
    # 좁히기(refine)는 이미 재검증된 목록에서만 만든다 → 회수 문서가 다시 나타나지 않음
    assert not names(svc.engine.refine(after, file_types=["docx"])) & {d.file_name for d in before if d.location == win.unc("docx")}
    # 한 폴더 전체 권한 회수 → 위치 필터 선택지에서도 해당 하위 경로 문서가 모두 빠짐
    win.fs.deny_read(UNC_ROOT + "\\데이터")
    after2 = svc.engine.list_visible_documents(user)
    assert not any("\\데이터\\" in d.location for d in after2)
    assert svc.engine.list_visible_documents(user, file_types=["csv"]) == []
    rec(f"{n0}건 → {n1}건 → {len(after2)}건")


def test_list_with_filters_is_verified_and_stale_index_not_modified(make_real, win):
    """입력조건: 분류·유형·위치·날짜 필터를 건 목록 조회 중 권한 회수
    예상결과: 필터를 건 조회도 동일하게 재검증하고, 조회가 색인을 바꾸지 않음(색인 세대 유지)"""
    svc, user, _ = ready(make_real, win, full=True)
    gen = svc.indexer.get_generation()
    allowed = svc.engine.list_visible_documents(user, file_types=["pdf", "docx"])
    assert {d.file_type for d in allowed} == {"pdf", "docx"}
    win.fs.deny_read(win.unc("pdf"))
    again = svc.engine.list_visible_documents(user, file_types=["pdf", "docx"], modified_from="2026-01-01")
    assert {d.file_type for d in again} == {"docx"}
    assert svc.indexer.get_generation() == gen


def test_virtual_demo_mode_list_unchanged(svc, users, rec):
    """입력조건: 데모(가상 사용자) 모드의 문서 목록
    예상결과: 기존 ACL 결과와 동일(재검증 정책이 데모 ACL 결과를 바꾸지 않음)"""
    u = users["actuary"]
    listed = svc.engine.list_visible_documents(u)
    assert {d.doc_id for d in listed} == {d.doc_id for d in svc.access.filter_documents(u, svc.indexer.list_documents(searchable_only=True))}
    assert len(listed) == 13
    rec(f"{len(listed)}건 동일")


# ============================================================ 4. 회귀 시나리오
def test_network_outage_then_recovery(make_real, win, rec):
    """입력조건: 공유 전체 오프라인 → 목록·검색·미리보기 → 복구
    예상결과: 오프라인 중에는 목록·경로·건수·결과·미리보기 모두 비어 있고(캐시 포함), 복구 후 색인 갱신 없이 다시 보이며 '없음' 결과가 캐시에 남지 않음"""
    svc, user, _ = ready(make_real, win, full=True)
    total = len(svc.engine.list_visible_documents(user))
    doc_id = svc.engine.search(user, Q).results[0].doc_id
    assert svc.engine.search(user, Q).from_cache
    win.fs.offline(UNC_ROOT)
    assert svc.engine.list_visible_documents(user) == []
    assert svc.engine.search(user, Q).results == []
    assert svc.engine.open_document(user, doc_id) is None and svc.engine.matching_chunks(user, doc_id, Q) == []
    assert svc.engine.search(user, Q).volatile  # 일시 장애 응답은 캐시하지 않음
    win.fs.offline(UNC_ROOT, False)
    assert len(svc.engine.list_visible_documents(user)) == total
    assert svc.engine.search(user, Q).results and svc.engine.open_document(user, doc_id) is not None
    rec(f"오프라인 0건 → 복구 {total}건")


def test_permission_revoked_then_restored(make_real, win):
    """입력조건: 권한 회수 → 확인 → 권한 복구 → 확인
    예상결과: 회수 중에는 어디에도 안 보이고, 복구하면 색인 갱신 없이 다시 표시됨. 회수 중 색인 갱신 시에는 색인에서 제거되고 복구 후 재색인으로 돌아옴"""
    svc, user, _ = ready(make_real, win, full=True)
    doc_id = next(d.doc_id for d in svc.engine.list_visible_documents(user) if d.location == win.unc("docx"))
    win.fs.deny_read(win.unc("docx"))
    assert doc_id not in {d.doc_id for d in svc.engine.list_visible_documents(user)}
    win.fs.allow(win.unc("docx"))
    assert doc_id in {d.doc_id for d in svc.engine.list_visible_documents(user)}
    win.fs.deny_read(win.unc("docx"))
    sync_with_audit(svc)
    assert svc.indexer.get_document(doc_id) is None
    win.fs.allow(win.unc("docx"))
    assert doc_id not in {d.doc_id for d in svc.engine.list_visible_documents(user)}  # 색인에 없으므로 갱신 전엔 없음
    sync_with_audit(svc)
    assert doc_id in {d.doc_id for d in svc.engine.list_visible_documents(user)}


def test_deleted_file_disappears_from_list_before_resync(make_real, win):
    """입력조건: 파일 삭제(색인 갱신 없음) → 목록 → 색인 갱신
    예상결과: 갱신 전에도 목록·건수에서 제외, 갱신 후 색인에서도 삭제"""
    svc, user, _ = ready(make_real, win, full=True)
    n0 = len(svc.engine.list_visible_documents(user))
    win.path("csv").unlink()
    after = svc.engine.list_visible_documents(user)
    assert len(after) == n0 - 1 and not any(d.location == win.unc("csv") for d in after)
    sync_with_audit(svc)
    assert len(svc.engine.list_visible_documents(user)) == n0 - 1


def test_modified_file_never_shows_old_paragraphs(make_real, win, rec):
    """입력조건: 본문 색인 후 원본 수정(색인 갱신 없음) — 검색 결과 문단, 미리보기, 일치 위치, AI 근거, 이전 답변
    예상결과: '원본 변경됨' 표시와 함께 과거 문단 본문이 어디에도 노출되지 않음. 색인 갱신 후에는 새 내용만 표시됨"""
    svc, user, _ = ready(make_real, win, full=True)
    first = svc.engine.search(user, Q)
    r0 = first.results[0]
    assert r0.passages and PHRASE in " ".join(p.text for p in r0.passages) or r0.passages
    entry = HistoryEntry(user.user_id, Q, "local", "답변", [(r.doc_id, r.title, r.content_hash) for r in first.results])
    assert not revalidate_history([entry], user, svc.indexer, svc.access)[0].hidden
    from helpers import make_docx
    make_docx(win.path("docx"), [("p", "새로 바뀐 문서 본문입니다 허용 오차 롤포워드 기준이 달라졌습니다.")], title="IFRS17 결산 검증 가이드")
    win.touch("docx", "2026-10-14")
    after = svc.engine.search(user, Q)
    r1 = next(r for r in after.results if r.doc_id == r0.doc_id)
    assert r1.stale and r1.passages == []
    doc, chunks = svc.engine.open_document(user, r0.doc_id)
    assert chunks == [] and svc.engine.matching_chunks(user, r0.doc_id, Q) == []
    assert all(PHRASE not in c.text for c in svc.answers.collect_citations(user, after))
    assert not any(c.doc_id == r0.doc_id for c in svc.answers.collect_citations(user, first))  # 과거 응답으로도 근거 불가
    assert revalidate_history([entry], user, svc.indexer, svc.access)[0].hidden
    sync_with_audit(svc)
    fresh = svc.engine.search(user, Q)
    top = next(r for r in fresh.results if r.doc_id == r0.doc_id)
    assert not top.stale and all(PHRASE not in p.text for p in top.passages)
    assert PHRASE.encode() not in svc.indexer.db_path.read_bytes()
    rec("수정 후 stale: 문단·미리보기·근거·이전 답변 비노출, 갱신 후 새 내용")


def test_vanished_mid_session_does_not_leak_name_or_path(make_real, win):
    """입력조건: 목록 조회 중 파일이 사라짐(vanish)
    예상결과: 해당 문서가 목록에서 제외됨"""
    svc, user, _ = ready(make_real, win, full=True)
    win.fs.vanish(win.unc("pptx"))
    assert not any(d.location == win.unc("pptx") for d in svc.engine.list_visible_documents(user))


# ============================================================ 5. 로컬 색인 저장 보안
@pytest.mark.skipif(os.name != "posix", reason="POSIX 권한 비트 검증")
def test_home_dir_is_owner_only(make_real, win):
    """입력조건: 실제 모드 서비스 생성
    예상결과: 색인 폴더 0700, index.db 0600"""
    svc, *_ = ready(make_real, win, full=True)
    assert (svc.indexer.db_path.parent.stat().st_mode & 0o077) == 0
    assert (svc.indexer.db_path.stat().st_mode & 0o077) == 0


def test_no_journal_or_temp_files_left_after_sync_and_reset(make_real, win, rec):
    """입력조건: 본문 색인 → 갱신 → 색인 삭제
    예상결과: 색인 폴더에 -journal/-wal/-shm/임시 파일이 남지 않고, 삭제 후 DB 바이트에 본문 문구가 없음"""
    svc, user, _ = ready(make_real, win, full=True)
    home = svc.indexer.db_path.parent
    sync_with_audit(svc)
    assert find_residue(home) == []
    assert PHRASE.encode() in svc.indexer.db_path.read_bytes()
    svc.indexer.reset()
    assert find_residue(home) == [] and PHRASE.encode() not in svc.indexer.db_path.read_bytes()
    rec("저널·임시 파일 없음, reset 후 본문 문구 없음")


def test_residue_purge_overwrites_backups_and_keeps_live_files(make_real, win, rec):
    """입력조건: 색인 폴더에 index.db.bak, 색인 복사본, 임시 파일이 남아 있음 → 서비스 기동
    예상결과: 기동 시 잔존 파일이 덮어쓰기 후 삭제되고 index.db·config·shares.json 은 유지됨"""
    svc, user, _ = ready(make_real, win, full=True)
    home = svc.indexer.db_path.parent
    data = svc.indexer.db_path.read_bytes()
    (home / "index.db.bak").write_bytes(data)
    (home / "index_old.db").write_bytes(data)
    (home / "x.tmp").write_bytes(b"temp")
    assert len(find_residue(home)) == 3 and any("잔존" in w or "남아" in w for w in storage_warnings(home))
    svc2 = build_real_services(home, fs=win.fs, identity=svc.identity)
    assert find_residue(home) == []
    assert (home / "index.db").exists() and (home / "shares.json").exists() and svc2.indexer.count_documents() > 0
    rec("잔존 3개 삭제, 라이브 파일 유지")


def test_wipe_file_overwrites_before_unlink(tmp_path):
    """입력조건: 본문이 든 파일을 wipe_file
    예상결과: 파일이 삭제되고 없는 파일도 오류 없이 처리"""
    f = tmp_path / "a.bak"
    f.write_bytes(PHRASE.encode() * 100)
    assert wipe_file(f) and not f.exists() and wipe_file(f)


def test_corrupt_index_is_discarded_and_rebuilt(make_real, win):
    """입력조건: 비정상 종료로 index.db 가 손상됨 → 서비스 기동
    예상결과: 손상 파일을 폐기하고 빈 색인으로 시작, 다시 색인 가능"""
    svc, user, _ = ready(make_real, win, full=True)
    home = svc.indexer.db_path.parent
    svc.indexer.db_path.write_bytes(b"corrupted" * 400)
    svc2 = build_real_services(home, fs=win.fs, identity=svc.identity)
    assert svc2.indexer.count_documents() == 0
    sync_with_audit(svc2)
    assert svc2.indexer.count_documents() > 0


def test_sync_folder_warning(tmp_path):
    """입력조건: 색인 폴더가 OneDrive 폴더 아래
    예상결과: 클라우드 동기화 경고 문구가 나옴"""
    p = tmp_path / "OneDrive - Corp" / "app"
    p.mkdir(parents=True)
    assert any("클라우드 동기화" in w for w in storage_warnings(p))


def test_db_pragmas_do_not_use_disk_temp(make_real, win):
    """입력조건: 파일 DB 연결
    예상결과: secure_delete=ON, temp_store=MEMORY, journal_mode=MEMORY"""
    svc, *_ = ready(make_real, win)
    with svc.indexer._conn() as c:
        assert c.execute("PRAGMA secure_delete").fetchone()[0] == 1
        assert c.execute("PRAGMA temp_store").fetchone()[0] == 2
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "memory"
