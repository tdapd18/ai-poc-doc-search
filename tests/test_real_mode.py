"""실제 Windows 공유폴더 모드 — 합성 Windows 공유(가상 데이터)로 검증. 실제 회사 PC/공유에는 연결하지 않는다."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from winshare import PHRASE, UNC_ROOT, normal_keys, unc  # noqa: E402

from core.app_config import ConfigError
from core.history import HistoryEntry, revalidate_history
from core.identity import WindowsIdentity
from core.metadata import auto_doc_id
from core.services import apply_index_mode, build_real_services, sync_with_audit
from core.shares import ShareError
from helpers import write_sidecar


def docs_by_file(svc):
    return {d.file_name: d for d in svc.indexer.list_documents(searchable_only=False)}


def ready(make_real, win, *, full=False, deny_read=(), deny_list=(), **kw):
    for p in deny_read:
        win.fs.deny_read(UNC_ROOT + "\\" + p)
    for p in deny_list:
        win.fs.deny_list(UNC_ROOT + "\\" + p)
    svc = make_real(full_text=full, **kw)
    rep = sync_with_audit(svc)
    return svc, svc.access.current_user(), rep


def db_bytes(svc) -> bytes:
    return svc.indexer.db_path.read_bytes()


# ============================================================ 공유 등록 검증 (요구 7·1)
def test_register_unc_validation(make_real, rec):
    """입력조건: 실제 UNC 등록 — 관리자 공유(C$), 장치 경로, 드라이브 경로, 슬래시 경로, 하위/상위 중복, 경로 구분자가 든 제외 패턴, 정상 등록
    예상결과: 위험·잘못된 입력은 ShareError 로 거부되고 정상 등록은 kind=unc 로 저장됨"""
    svc = make_real(register=False)
    reg = svc.shares
    bad = ["\\\\srv\\C$", "\\\\srv\\admin$\\x", "\\\\?\\UNC\\srv\\share", "\\\\.\\pipe\\x", "C:\\temp", "//srv/share", "\\\\srv", ""]
    for b in bad:
        with pytest.raises(ShareError):
            reg.register_unc("공유", b)
    with pytest.raises(ShareError):
        reg.register_unc("공유", "\\\\srv\\share", exclude=["a\\b"])
    s = reg.register_unc("계리", "\\\\srv.example.invalid\\share\\계리", exclude=["Archive*", " "])
    assert s.kind == "unc" and s.exclude == ("Archive*",) and reg.list()[0].kind == "unc"
    for dup in ("\\\\SRV.example.invalid\\Share\\계리", "\\\\srv.example.invalid\\share", "\\\\srv.example.invalid\\share\\계리\\하위"):
        with pytest.raises(ShareError, match="겹치는|등록된"):
            reg.register_unc("다른이름", dup)
    with pytest.raises(ShareError, match="같은 표시 이름"):
        reg.register_unc("계리", "\\\\other.example.invalid\\x")
    rec("관리자 공유·장치 경로·중복·겹침 거부 확인")


# ============================================================ 메타데이터 전용 (요구 5)
def test_metadata_only_never_reads_file_content(make_real, win, rec):
    """입력조건: 기본 설정(메타데이터 전용)으로 합성 공유를 색인
    예상결과: 파일 내용을 읽은 횟수 0(reads=[]), 권한 확인용 열기만 수행, 본문 조각·본문 텍스트가 색인 DB 어디에도 없음(고유 문구 미존재)"""
    svc, user, rep = ready(make_real, win, deny_read=["기밀"])
    assert win.fs.reads == [] and len(win.fs.opens) >= 12
    docs = svc.indexer.list_documents(searchable_only=False)
    assert docs and all(d.index_level == "metadata" and d.body == "" for d in docs)
    assert all(svc.indexer.get_chunks(d.doc_id) == [] for d in docs)
    assert PHRASE.encode("utf-8") not in db_bytes(svc)
    rec(f"문서 {len(docs)}건 색인, 본문 읽기 {len(win.fs.reads)}회, 열기 확인 {len(win.fs.opens)}회")


def test_metadata_only_search_by_name_path_and_body_notice(make_real, win):
    """입력조건: 메타데이터 전용에서 파일명·폴더명·확장자로 검색, 본문 용어로 검색, 본문만 범위로 검색
    예상결과: 파일명·폴더 경로로는 찾고, 본문 용어는 못 찾으며, 본문만 범위는 결과 없음 + 본문 미색인 문서 수 안내"""
    svc, user, _ = ready(make_real, win)
    by_name = svc.engine.search(user, "검증결과 집계", top_k=10)
    assert by_name.results[0].file_name == "모델별_검증결과_집계 (최종).xlsx"
    by_folder = svc.engine.search(user, "옛날 결산문서", top_k=10)
    assert by_folder.results and by_folder.results[0].file_type == "doc"
    in_folder = svc.engine.search(user, "폴더이름 이십오자가량의긴이름03", top_k=10)  # 폴더 경로 검색
    assert any(r.file_name == "깊은문서.txt" for r in in_folder.results)
    assert svc.engine.search(user, PHRASE, top_k=10).status == "no_results"
    body_only = svc.engine.search(user, "검증결과", scope="body")
    assert body_only.status == "no_results" and body_only.metadata_only_count > 5
    r = by_name.results[0]
    assert r.index_level == "metadata" and r.passages == () and r.location == unc(win.rel["xlsx"])


def test_full_text_requires_approval_and_switch_resets_index(make_real, win, rec):
    """입력조건: 승인 없이 본문 모드 전환 시도 → 승인 후 전환 → 본문 색인 → 다시 메타데이터 전용으로 전환
    예상결과: 승인 없으면 거부, 전환 시 색인 초기화(문서 0건), 본문 모드에서는 본문이 색인되고, 되돌리면 본문(고유 문구)이 DB 파일에서도 사라짐"""
    svc, user, _ = ready(make_real, win)
    assert svc.indexer.count_documents() > 0
    with pytest.raises(ConfigError):
        apply_index_mode(svc, "full_text")
    assert svc.config.index_mode == "metadata_only" and svc.indexer.count_documents() > 0  # 거부 시 색인 유지
    assert apply_index_mode(svc, "full_text", approver="SEC-1", acknowledged=True) is True
    assert svc.indexer.count_documents() == 0
    sync_with_audit(svc)
    assert svc.engine.search(user, PHRASE).results and PHRASE.encode("utf-8") in db_bytes(svc)
    assert apply_index_mode(svc, "metadata_only") is True
    assert svc.indexer.count_documents() == 0 and PHRASE.encode("utf-8") not in db_bytes(svc)
    assert not svc.config.approval.approved
    rec("본문 모드 전환/복귀 시 색인 초기화, 복귀 후 DB 에 본문 문구 없음")


# ============================================================ 자동 색인 (요구 3, 4)
def test_auto_index_without_meta_json_and_metadata_derivation(make_real, win, rec):
    """입력조건: .meta.json 없이 합성 업무문서를 본문 모드로 색인
    예상결과: 문서 ID(F-…, 경로 기반), 제목(문서 속성/파일명), 버전(파일명 패턴), 분류(키워드), 부서(상위 폴더), 수정일(파일 시각)이 자동 도출되고 형식별 위치가 기록됨"""
    svc, user, rep = ready(make_real, win, full=True, deny_read=["기밀"], deny_list=["목록거부"])
    d = docs_by_file(svc)
    docx = d["IFRS17 결산 검증 가이드_v2.1.docx"]
    assert docx.doc_id == auto_doc_id(unc(win.rel["docx"])) and docx.doc_id.startswith("F-")
    assert (docx.title, docx.version, docx.category, docx.department, docx.modified_at) == \
           ("IFRS17 결산 검증 가이드", "2.1", "IFRS17", "결산", "2026-10-09")
    assert docx.location == unc(win.rel["docx"]) and docx.share == "계리평가팀" and docx.file_type == "docx"
    assert d["모델별_검증결과_집계 (최종).xlsx"].version == "최종"
    assert d["GoC_변동_2026-09.csv"].category == "IFRS17"  # 파일 내용이 아닌 이름/경로 키워드(GoC)
    assert d["메모.txt"].category == "결산" or d["메모.txt"].category == "기타"
    locs = {f: [c.loc for c in svc.indexer.get_chunks(doc.doc_id)] for f, doc in d.items()}
    assert any(l.startswith("문단") for l in locs["IFRS17 결산 검증 가이드_v2.1.docx"])
    assert "표 1 · 행 2" in locs["IFRS17 결산 검증 가이드_v2.1.docx"]
    assert "시트 '요약' · 셀 A2:C2" in locs["모델별_검증결과_집계 (최종).xlsx"]
    assert "슬라이드 2" in locs["월말결산 킥오프.PPTX"] and "p.2" in locs["내부통제 점검보고서.pdf"]
    assert "행 2" in locs["GoC_변동_2026-09.csv"] and any(l.startswith("줄") for l in locs["메모.txt"])
    rec(f"{len(d)}건: " + ", ".join(sorted(d))[:120])


def test_cp949_text_and_csv_are_decoded(make_real, win):
    """입력조건: CP949 로 저장된 한글 TXT/CSV (한국어 Windows 기본 저장 형식)
    예상결과: 글자가 깨지지 않고 본문 검색이 됨"""
    svc, user, _ = ready(make_real, win, full=True)
    assert "메모.txt" in [r.file_name for r in svc.engine.search(user, "결산 마감 전 확인할 사항", top_k=10).results]
    hit = next(r for r in svc.engine.search(user, "GoC-C07 변동률", top_k=10).results if r.file_name == "GoC_변동_2026-09.csv")
    assert any("GoC-C07" in p.text and "6.2%" in p.text for p in hit.passages)


def test_front_matter_and_sidecar_override_auto_metadata(make_real, win):
    """입력조건: 머리말(--- 메타데이터)이 있는 MD, 옆에 .meta.json 이 있는 DOCX
    예상결과: 명시된 메타데이터(doc_id MD-777, 제목·분류)가 자동 도출값보다 우선 (.meta.json 은 선택 사항)"""
    write_sidecar(win.path("docx"), doc_id="DOCX-1", title="재정의된 제목", category="RAFM", version="7")
    svc, user, _ = ready(make_real, win, full=True)
    d = docs_by_file(svc)
    assert d["front.md"].doc_id == "MD-777" and d["front.md"].version == "9.9" and d["front.md"].department == "모델팀"
    over = d["IFRS17 결산 검증 가이드_v2.1.docx"]
    assert (over.doc_id, over.title, over.category, over.version) == ("DOCX-1", "재정의된 제목", "RAFM", "7")
    assert over.location == unc(win.rel["docx"])  # 위치는 항상 실제 경로


def test_excluded_unsupported_legacy_and_error_files_are_reported(make_real, win, rec):
    """입력조건: 잠금(~$)·Thumbs.db·desktop.ini·숨김·이미지·구형(.doc/.xls)·암호화 DOCX·손상 XLSX·0바이트 TXT 가 섞인 공유
    예상결과: 임시/시스템/숨김 파일은 제외, 이미지는 미지원 집계, 구형은 파일명 검색만(메타 수준), 암호화·손상·빈 파일은 사유와 함께 보고(앱은 계속 동작)"""
    svc, user, rep = ready(make_real, win, full=True)
    sr = rep.sources[0]
    names = set(docs_by_file(svc))
    assert not names & {"~$IFRS17 결산 검증 가이드_v2.1.docx", "Thumbs.db", "desktop.ini", ".숨김메모.txt", "사진.png"}
    assert {"옛날 결산문서.doc", "옛날 표.xls"} <= names
    assert docs_by_file(svc)["옛날 표.xls"].index_level == "metadata" and docs_by_file(svc)["옛날 표.xls"].file_type == "xls"
    reasons = {i.path.split("/")[-1]: i.reason for i in sr.invalid}
    assert "암호" in reasons["암호화된 문서.docx"] and "손상" in reasons["깨진 집계.xlsx"] and "비어" in reasons["빈 메모.txt"]
    assert sr.skipped["지원하지 않는 형식"] == 1 and sr.skipped["구형/미지원 형식 — 파일명 검색만"] == 2
    rec(f"invalid={sorted(reasons)}, skipped={sr.skipped}")


def test_large_file_falls_back_to_metadata_level(make_real, win):
    """입력조건: 크기 한도(1MB)를 넘는 CSV
    예상결과: 본문은 읽지 않고(읽기 호출 없음) 파일명 검색만 가능한 메타데이터 수준으로 색인하고 사유를 보고"""
    big = win.local / "대용량.csv"
    big.write_bytes(("a,b\n" + "x,y\n" * 400_000).encode())
    svc, user, rep = ready(make_real, win, full=True, max_mb=1)
    d = docs_by_file(svc)["대용량.csv"]
    assert d.index_level == "metadata" and d.size_bytes > 1_000_000
    assert unc("대용량.csv").casefold() not in win.fs.reads
    assert any("크기 한도(1MB) 초과" in k for k in rep.sources[0].skipped)


def test_same_names_special_chars_long_paths_and_case_insensitive_ids(make_real, win):
    """입력조건: 같은 이름 다른 폴더, 특수문자 이름, 6단계 긴 폴더명(경로 260자 초과), 대소문자만 다른 경로
    예상결과: 모두 별도 문서로 색인(중복 오류 없음), 경로 대소문자만 다르면 같은 문서 ID"""
    svc, user, rep = ready(make_real, win, full=True)
    docs = svc.indexer.list_documents(searchable_only=False)
    assert sum(1 for d in docs if d.file_name == "보고서.txt") == 2
    assert any(d.file_name == "결산 [최종] #1 & 검토.txt" for d in docs)
    deep = next(d for d in docs if d.file_name == "깊은문서.txt")
    assert len(deep.location) > 260 and deep.location == unc(win.rel["deep"])
    assert not rep.sources[0].duplicates
    assert auto_doc_id(deep.location.upper()) == deep.doc_id


# ============================================================ 증분 수집 (요구 6)
def test_incremental_sync_rereads_only_changed_but_rechecks_permission(make_real, win, rec):
    """입력조건: 변경 없이 색인 갱신을 다시 실행 → 파일 1개 수정 후 다시 실행
    예상결과: 변경 없는 파일은 본문을 다시 읽지 않고(reads 불변) 권한 확인용 열기만 다시 수행, 수정한 파일만 다시 읽어 갱신(수정 1건)"""
    svc, user, rep1 = ready(make_real, win, full=True)
    n_docs = svc.indexer.count_documents()
    reads, opens = len(win.fs.reads), len(win.fs.opens)
    rep2 = sync_with_audit(svc)
    s2 = rep2.sources[0]
    reads_after_2 = len(win.fs.reads)
    n_invalid = len(rep1.sources[0].invalid)  # 오류 파일(암호화·손상·빈 파일)은 색인되지 않아 매번 다시 확인한다
    assert len(win.fs.reads) - reads == n_invalid and len(win.fs.opens) - opens >= n_docs - 2
    assert not rep2.changed and s2.unchanged >= n_docs - 2 and not s2.added and not s2.deleted
    win.path("csv").write_bytes("GoC,기초 CSM,기말 CSM,변동률\nGoC-A01,1200,1197,-0.3%\nGoC-C07,640,700,9.9%".encode("cp949"))
    win.touch("csv", "2026-10-13")
    rep3 = sync_with_audit(svc)
    assert len(win.fs.reads) - reads_after_2 == n_invalid + 1 and len(rep3.sources[0].updated) == 1
    assert svc.engine.search(user, "GoC-C07 9.9%").results
    rec(f"재색인 시 정상 문서 중 본문을 다시 읽은 것은 수정된 1개뿐(오류 파일 {n_invalid}건은 매번 재확인)")


def test_rename_is_delete_plus_add(make_real, win):
    """입력조건: 파일 이름 변경
    예상결과: 이전 경로 문서는 삭제, 새 경로 문서는 신규(경로 기반 ID 이므로)"""
    svc, user, _ = ready(make_real, win, full=True)
    old = win.path("txt_cp949")
    old.rename(old.with_name("메모_이름변경.txt"))
    s = sync_with_audit(svc).sources[0]
    assert len(s.deleted) == 1 and len(s.added) == 1
    assert svc.engine.search(user, "메모 이름변경", scope="name").results[0].file_name == "메모_이름변경.txt"


def test_progress_callback_and_audit_log_without_names(make_real, win):
    """입력조건: 진행률 콜백을 주고 색인 → 감사 로그 확인
    예상결과: 마지막 이벤트가 done 이고 파일 수가 보고되며, 감사 로그에는 건수만 있고 파일명·경로·본문은 없음"""
    svc = make_real()
    events = []
    sync_with_audit(svc, events.append)
    assert events[-1].get("done") and events[-1]["files"] >= 20
    log = svc.config_store.audit_path.read_text(encoding="utf-8")
    assert '"added"' in log and "결산" not in log and "fs-corp01" not in log and PHRASE not in log


# ============================================================ 권한 (요구 2, 6)
def test_unreadable_files_and_folders_are_not_indexed(make_real, win, rec):
    """입력조건: 파일 읽기 거부(기밀 폴더)와 폴더 목록 거부(목록거부 폴더)가 있는 공유
    예상결과: 두 곳의 문서는 색인되지 않고 '읽기 권한 없음 N건'으로 건수만 보고(파일명 미노출), 나머지는 정상 색인"""
    svc, user, rep = ready(make_real, win, full=True, deny_read=["기밀"], deny_list=["목록거부"])
    names = set(docs_by_file(svc))
    assert "인사 평가표.docx" not in names and "안쪽 문서.txt" not in names
    assert svc.indexer.count_documents() == 14  # 정상 12 + 구형 2 (오류 파일 3, 접근 거부 2 제외)
    sr = rep.sources[0]
    assert sr.denied == 2
    assert all("인사" not in line and "기밀" not in line for line in rep.summary_lines())
    assert svc.engine.search(user, "인사 평가표", scope="name").status == "no_results"
    rec(f"색인 {svc.indexer.count_documents()}건, 권한 없음 {sr.denied}건 집계")


def test_revoked_permission_is_hidden_immediately_everywhere(make_real, win, rec):
    """입력조건: 색인 후 DOCX 의 읽기 권한이 회수됨(색인 갱신 전) — 검색·캐시·미리보기·원문 위치·AI 근거·이전 답변
    예상결과: 색인 갱신을 기다리지 않고 모든 곳에서 즉시 숨김. 캐시 적중 결과도 재검증으로 폐기"""
    svc, user, _ = ready(make_real, win, full=True)
    q = "결산 검증 허용 오차 롤포워드"
    first = svc.engine.search(user, q)
    assert first.results[0].file_name.endswith("v2.1.docx") and svc.engine.search(user, q).from_cache
    doc_id = first.results[0].doc_id
    entry = HistoryEntry(user.user_id, q, "local", "답변", [(r.doc_id, r.title, r.content_hash) for r in first.results])
    assert not revalidate_history([entry], user, svc.indexer, svc.access)[0].hidden
    win.fs.deny_read(win.unc("docx"))
    after = svc.engine.search(user, q)
    assert not after.from_cache and doc_id not in [r.doc_id for r in after.results]
    assert svc.engine.open_document(user, doc_id) is None
    assert svc.engine.matching_chunks(user, doc_id, q) == []
    ans = svc.answers.local_answer(user, first)  # 이전 검색 결과로 답변을 만들어도 회수된 문서는 근거에서 제외
    assert doc_id not in {c.doc_id for c in ans.citations}
    assert revalidate_history([entry], user, svc.indexer, svc.access)[0].hidden
    rec("검색/캐시/미리보기/위치/AI 근거/이전 답변에서 즉시 숨김")


def test_revoked_then_synced_removes_index_and_restored_comes_back(make_real, win):
    """입력조건: 권한 회수 → 색인 갱신 → 권한 복구 → 색인 갱신
    예상결과: 갱신 시 색인·조각이 삭제되고(권한 없음 집계), 복구 후 갱신하면 다시 색인됨"""
    svc, user, _ = ready(make_real, win, full=True)
    doc_id = auto_doc_id(win.unc("docx"))
    assert svc.indexer.get_document(doc_id)
    win.fs.deny_read(win.unc("docx"))
    s = sync_with_audit(svc).sources[0]
    assert s.denied == 1 and doc_id in s.deleted
    assert svc.indexer.get_document(doc_id) is None and svc.indexer.get_chunks(doc_id) == []
    win.fs.allow(win.unc("docx"))
    s2 = sync_with_audit(svc).sources[0]
    assert doc_id in s2.added and svc.engine.search(user, "허용 오차 롤포워드").results


def test_permission_revoked_on_unchanged_file_is_detected_by_recheck(make_real, win):
    """입력조건: 파일 내용·수정시각은 그대로이고 권한만 회수(ACL 변경은 mtime 을 바꾸지 않음) 후 색인 갱신
    예상결과: 증분 수집이 '변경 없음'으로 건너뛰지 않고 권한을 재확인해 색인에서 제거"""
    svc, user, _ = ready(make_real, win, full=True)
    doc_id = auto_doc_id(win.unc("pdf"))
    win.fs.deny_read(win.unc("pdf"))
    s = sync_with_audit(svc).sources[0]
    assert doc_id in s.deleted and svc.indexer.get_document(doc_id) is None


def test_denied_subfolder_removes_its_documents_failclosed(make_real, win):
    """입력조건: 색인 후 하위 폴더('데이터') 목록 권한이 회수됨
    예상결과: 그 폴더 아래 문서(CSV·TXT)가 색인에서 제거되고 다른 폴더 문서는 유지"""
    svc, user, _ = ready(make_real, win, full=True)
    before = svc.indexer.count_documents()
    win.fs.deny_list(UNC_ROOT + "\\데이터")
    s = sync_with_audit(svc).sources[0]
    names = set(docs_by_file(svc))
    assert "GoC_변동_2026-09.csv" not in names and "메모.txt" not in names and "RAFM_오류대응_FAQ.md" in names
    assert svc.indexer.count_documents() == before - 2 and s.denied >= 1


def test_other_windows_account_gets_its_own_clean_index(make_real, win, tmp_path, rec):
    """입력조건: 같은 홈 폴더를 다른 Windows 계정으로 열기 / 대소문자만 다른 같은 계정으로 열기
    예상결과: 다른 계정이면 색인을 폐기(본문 문구도 DB 에서 제거), 같은 계정(대소문자 무시)이면 유지"""
    home = tmp_path / "shared_home"
    svc, user, _ = ready(make_real, win, full=True, home=home)
    n = svc.indexer.count_documents()
    assert n > 0
    same = build_real_services(home, fs=win.fs, identity=WindowsIdentity("corp", "TESTER"))
    assert same.indexer.count_documents() == n
    other = build_real_services(home, fs=win.fs, identity=WindowsIdentity("CORP", "someone_else"))
    assert other.indexer.count_documents() == 0 and PHRASE.encode("utf-8") not in db_bytes(other)
    rec("다른 계정 접근 시 색인 폐기")


def test_identity_gate(make_real, win):
    """입력조건: 다른 사용자 신원으로 검색/열기 시도
    예상결과: 현재 Windows 계정이 아니면 어떤 문서도 접근 불가(denied)"""
    svc, user, _ = ready(make_real, win, full=True)
    from core.access_control import User
    stranger = User("CORP\\other", "other", "", "member", ())
    assert svc.engine.search(stranger, "결산").status == "denied"
    d = next(iter(svc.indexer.list_documents()))
    assert svc.engine.open_document(stranger, d.doc_id) is None
    assert svc.access.get_user("CORP\\other") is None and svc.access.get_user(user.user_id) is not None


# ============================================================ 파일 변경·삭제·장애 (요구 6)
def test_deleted_file_hidden_immediately_and_secure_deleted_after_sync(make_real, win, rec):
    """입력조건: 파일 삭제 → (갱신 전) 검색 → 색인 갱신 → 색인 파일 확인
    예상결과: 갱신 전에도 조회에서 숨김, 갱신 후 색인·조각 삭제, 색인 DB 파일 바이트에 본문 고유 문구가 남지 않음(secure_delete)"""
    svc, user, _ = ready(make_real, win, full=True)
    assert PHRASE.encode("utf-8") in db_bytes(svc)
    doc_id = auto_doc_id(win.unc("docx"))
    win.path("docx").unlink()
    assert doc_id not in [r.doc_id for r in svc.engine.search(user, "허용 오차 롤포워드").results]
    assert svc.engine.open_document(user, doc_id) is None
    s = sync_with_audit(svc).sources[0]
    assert doc_id in s.deleted and svc.indexer.get_chunks(doc_id) == []
    assert PHRASE.encode("utf-8") not in db_bytes(svc)
    rec("삭제 후 DB 바이트에 본문 문구 없음")


def test_modified_file_shows_stale_until_resync(make_real, win):
    """입력조건: 색인 후 파일 수정(갱신 전) → 갱신
    예상결과: 갱신 전에는 '원본이 변경됨(stale)' 표시, 갱신 후에는 표시 없음"""
    svc, user, _ = ready(make_real, win, full=True)
    q = "결산 검증 허용 오차"
    assert svc.engine.search(user, q).results[0].stale is False
    from helpers import make_docx
    make_docx(win.path("docx"), [("p", "수정된 문서의 본문입니다 허용 오차 기준이 바뀌었습니다.")], title="IFRS17 결산 검증 가이드")
    win.touch("docx", "2026-10-14")
    stale = svc.engine.search(user, q)
    assert stale.results[0].stale is True and not stale.from_cache
    sync_with_audit(svc)
    assert svc.engine.search(user, q).results[0].stale is False


def test_share_offline_hides_results_but_keeps_index_and_recovers(make_real, win, rec):
    """입력조건: 공유 전체가 오프라인(VPN 단절) 상태에서 검색·색인 갱신 → 복구
    예상결과: 검색 결과는 숨김, 색인 갱신은 해당 공유를 '연결할 수 없음'으로 보고하고 기존 색인을 지우지 않음, 복구 후 재색인 없이 다시 검색됨"""
    svc, user, _ = ready(make_real, win, full=True)
    n = svc.indexer.count_documents()
    win.fs.offline(UNC_ROOT)
    assert svc.engine.search(user, "결산 검증 허용 오차").status == "no_results"
    s = sync_with_audit(svc).sources[0]
    assert s.unavailable_shares == ["계리평가팀"] and s.retained == n and not s.deleted
    assert svc.indexer.count_documents() == n
    assert any("연결할 수 없" in l for l in sync_with_audit(svc).summary_lines())
    win.fs.offline(UNC_ROOT, False)
    assert svc.engine.search(user, "결산 검증 허용 오차").results
    rec(f"오프라인 중 색인 {n}건 유지, 복구 후 즉시 검색")


def test_subfolder_transient_error_retains_only_that_subtree(make_real, win):
    """입력조건: 하위 폴더('결산')만 일시적으로 연결 불가인 상태에서 색인 갱신
    예상결과: 그 폴더 아래 문서는 삭제하지 않고 유지(조회 시 숨김), 나머지는 정상 처리"""
    svc, user, _ = ready(make_real, win, full=True)
    before = svc.indexer.count_documents()
    win.fs.offline(UNC_ROOT + "\\결산")
    s = sync_with_audit(svc).sources[0]
    assert svc.indexer.count_documents() == before and s.retained >= 4 and not s.deleted
    assert svc.engine.search(user, "허용 오차 롤포워드").status == "no_results"  # 결산 폴더 문서는 숨김
    assert svc.engine.search(user, "RAFM 오류대응").results  # 다른 폴더는 정상
    win.fs.offline(UNC_ROOT + "\\결산", False)
    assert svc.engine.search(user, "허용 오차 롤포워드").results


def test_locked_file_is_retained_not_deleted(make_real, win):
    """입력조건: 색인된 파일이 다른 프로그램에 잠김(공유 위반) 상태에서 수정 후 색인 갱신
    예상결과: 기존 색인을 지우지 않고 재시도 대상으로 보고, 조회에서는 숨김, 잠금 해제 후 갱신하면 최신 내용 반영"""
    svc, user, _ = ready(make_real, win, full=True)
    doc_id = auto_doc_id(win.unc("csv"))
    win.path("csv").write_bytes("GoC,기초 CSM\nGoC-Z99,1".encode("cp949"))
    win.touch("csv", "2026-10-14")
    win.fs.lock(win.unc("csv"))
    s = sync_with_audit(svc).sources[0]
    assert svc.indexer.get_document(doc_id) and doc_id not in s.deleted and s.retained >= 1
    assert any("재시도" in k for k in s.skipped)
    assert doc_id not in [r.doc_id for r in svc.engine.search(user, "GoC 변동률").results]
    win.fs.lock(win.unc("csv"), False)
    sync_with_audit(svc)
    assert svc.engine.search(user, "GoC-Z99").results


def test_file_changed_while_reading_is_skipped_and_old_index_kept(make_real, win):
    """입력조건: 파일을 읽는 도중 내용이 바뀜(읽기 직후 수정 시각 불일치)
    예상결과: 불완전한 내용을 색인하지 않고 기존 색인을 유지하며 재시도 대상으로 보고, 안정되면 반영"""
    svc, user, _ = ready(make_real, win, full=True)
    doc_id = auto_doc_id(win.unc("csv"))
    old_hash = svc.indexer.content_hash_of(doc_id)
    win.path("csv").write_bytes("GoC,값\nGoC-V1,1".encode("cp949"))
    win.touch("csv", "2026-10-13")

    def mutate(path):  # 읽기 시작 직전 다른 사용자가 다시 저장
        if path.casefold().endswith("goc_변동_2026-09.csv"):
            win.path("csv").write_bytes("GoC,값\nGoC-V2,2".encode("cp949"))
            win.touch("csv", "2026-10-14")
    win.fs.on_read = mutate
    s = sync_with_audit(svc).sources[0]
    assert svc.indexer.content_hash_of(doc_id) == old_hash and any("재시도" in k for k in s.skipped)
    win.fs.on_read = None
    sync_with_audit(svc)
    text = " ".join(c.text for c in svc.indexer.get_chunks(doc_id))
    assert "GoC-V2" in text and "GoC-V1" not in text


def test_file_cap_makes_scan_partial_and_does_not_delete(make_real, win):
    """입력조건: 파일 수 한도를 낮춰 부분 수집이 된 색인 갱신
    예상결과: 확인하지 못한 문서를 삭제하지 않고 유지하며 부분 수집 경고를 보고"""
    svc, user, _ = ready(make_real, win, full=True)
    n = svc.indexer.count_documents()
    svc.config.max_files_per_share = 5
    s = sync_with_audit(svc).sources[0]
    assert svc.indexer.count_documents() == n and not s.deleted
    assert any("파일 수 한도" in w for w in s.warnings)


def test_share_specific_exclude_patterns(make_real, win):
    """입력조건: 공유 단위 제외 패턴('구형', 'A')
    예상결과: 해당 이름의 폴더 아래 문서는 색인하지 않음"""
    svc = make_real(register=False, full_text=True)
    svc.shares.register_unc("계리평가팀", UNC_ROOT, exclude=["구형", "A"])
    sync_with_audit(svc)
    names = {(d.file_name, d.location) for d in svc.indexer.list_documents(searchable_only=False)}
    assert not any("구형" in loc or "\\A\\" in loc for _, loc in names) and any(n == "보고서.txt" for n, _ in names)


def test_disabled_or_removed_share_removes_documents(make_real, win):
    """입력조건: 공유를 사용 안 함으로 바꾸거나 등록 해제한 뒤 색인 갱신
    예상결과: 그 공유의 문서가 색인에서 모두 삭제됨 (삭제된 내용은 DB 에 남지 않음)"""
    svc, user, _ = ready(make_real, win, full=True)
    svc.shares.set_enabled("계리평가팀", False)
    s = sync_with_audit(svc).sources[0]
    assert svc.indexer.count_documents() == 0 and len(s.deleted) >= 12
    assert PHRASE.encode("utf-8") not in db_bytes(svc)


def test_index_file_is_private_on_posix(make_real, win):
    """입력조건: 개인 색인 DB / 설정 파일 생성
    예상결과: 본인만 읽고 쓸 수 있는 권한(600). Windows 에서는 사용자 프로필 폴더의 기본 ACL 에 의존(문서화)"""
    if os.name != "posix":
        pytest.skip("posix 전용")
    svc, user, _ = ready(make_real, win)
    assert oct(svc.indexer.db_path.stat().st_mode)[-3:] == "600"
    assert oct(svc.config_store.path.stat().st_mode)[-3:] == "600" if svc.config_store.path.exists() else True
