from core.access_control import AccessController, User
from core.history import HistoryEntry, revalidate_history
from core.models import Document

GOC = "GoC 단위 변동 분석 방법"  # SF-002 (계리평가팀 전용)


def _edit_acl(path, new_line):
    text = path.read_text(encoding="utf-8")
    lines = [new_line if l.startswith("allowed_groups:") else l for l in text.splitlines()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_visible_documents_differ_by_user(svc, users, rec):
    """입력조건: 계리평가팀/재무팀/관리자 가상 사용자별 접근 가능 문서
    예상결과: 계리 9건, 재무 3건(SF-001, GW-002, BS-002), 관리자 10건"""
    ids = {k: sorted(d.doc_id for d in svc.engine.list_visible_documents(u)) for k, u in users.items()}
    rec(", ".join(f"{k}={len(v)}" for k, v in ids.items()))
    assert len(ids["actuary"]) == 9 and "SF-004" not in ids["actuary"]
    assert ids["finance"] == ["BS-002", "GW-002", "SF-001"]
    assert len(ids["admin"]) == 10


def test_unauthorized_documents_not_searchable(svc, users, rec):
    """입력조건: 재무팀 사용자가 RAFM FAQ·GoC 매뉴얼·관리자 전용 문서 주제를 검색
    예상결과: 권한 없는 문서(GW-001, SF-002, SF-004, BS-001 ...)가 결과에 전혀 없음"""
    banned = {"GW-001", "GW-003", "SF-002", "SF-003", "SF-004", "BS-001", "BS-003"}
    seen = set()
    for q in ["RAFM 모델 실행 오류 E101", GOC, "예외 승인 내역", "모델별 검증 체크리스트", "계리적 가정 변경 승인"]:
        seen |= {r.doc_id for r in svc.engine.search(users["finance"], q).results}
    rec(f"재무팀 결과 문서: {sorted(seen)}")
    assert not seen & banned


def test_admin_only_doc_hidden_from_actuary(svc, users):
    """입력조건: '예외 승인 내역' 검색 (계리 vs 관리자)
    예상결과: 계리평가팀은 SF-004 미노출, 관리자는 SF-004 노출"""
    q = "결산 검증 예외 승인 내역"
    assert "SF-004" not in [r.doc_id for r in svc.engine.search(users["actuary"], q).results]
    assert "SF-004" in [r.doc_id for r in svc.engine.search(users["admin"], q).results]


def test_no_side_channel_counts(svc, users, rec):
    """입력조건: 계리 전용 문서와 겹치는 질문을 재무팀(접근 가능 문서 3건)이 검색, 비인가 문서 전용 주제도 검색
    예상결과: 일치 건수·결과가 재무팀 접근 가능 문서(최대 3건)만으로 계산되고, 메시지에 '권한/제외' 등 비인가 문서 존재를 암시하는 표현 없음"""
    visible = {"SF-001", "GW-002", "BS-002"}
    for q in ["RAFM 모델 실행 오류 E101 대응", "결산 검증 예외 승인 내역 관리자", "GoC 변동 분석 매뉴얼"]:
        r = svc.engine.search(users["finance"], q)
        rec(f"{q} → status={r.status}, total_matched={r.total_matched}, 결과={[x.doc_id for x in r.results]}")
        assert {x.doc_id for x in r.results} <= visible
        assert r.total_matched == len(r.results) <= 3
        assert "권한" not in r.message and "제외" not in r.message and "숨" not in r.message
    # 비인가 문서에만 해당하는 고유 용어는 정확히 '결과 없음' 과 동일하게 보인다
    r = svc.engine.search(users["finance"], "EX-2026-031 GoC-C07 가정위원회")
    assert r.total_matched == len(r.results)


def test_unauthorized_preview_blocked(svc, users):
    """입력조건: 재무팀 사용자가 GW-001/SF-004 원문 열기 시도, 존재하지 않는 ID 열기
    예상결과: 모두 None (존재/권한 여부를 구분하지 않음), 권한자는 열람 가능"""
    assert svc.engine.open_document(users["finance"], "GW-001") is None
    assert svc.engine.open_document(users["actuary"], "SF-004") is None
    assert svc.engine.open_document(users["finance"], "NOPE-1") is None
    doc, chunks = svc.engine.open_document(users["actuary"], "GW-001")
    assert doc.doc_id == "GW-001" and chunks


def test_default_deny_rules():
    """입력조건: ACL 이 비어 있는 문서, 알 수 없는 사용자, None 사용자
    예상결과: 모두 거부 (기본 거부 정책)"""
    user = User("u1", "x", "d", "member", ("g1",))
    ac = AccessController([user])
    doc = Document("D-1", "t", "s", "S", "기타", "1", "2026-01-01", "2026-01-01", "d", "l", "body")
    assert ac.can_access(user, doc) is False
    assert ac.can_access(None, doc) is False
    assert ac.can_access(User("ghost", "x", "d", "admin", ()), doc) is False
    doc2 = Document(**{**doc.__dict__, "allowed_groups": ("g1",)})
    assert ac.can_access(user, doc2) is True


def test_unknown_user_gets_denied_search(svc):
    """입력조건: 등록되지 않은 사용자/None 으로 검색
    예상결과: status=denied, 결과 없음 (비정상 종료 없음)"""
    assert svc.engine.search(None, "결산").status == "denied"
    assert svc.engine.search(User("ghost", "x", "d", "admin", ()), "결산").status == "denied"


def test_acl_grant_reflected_after_sync(svc, users, data_copy, rec):
    """입력조건: SF-002(GoC 매뉴얼)의 allowed_groups 에 finance 추가 후 색인 갱신
    예상결과: 갱신 전에는 재무팀 검색 불가, 갱신 후 검색/열람 가능, 권한변경 1건 감지"""
    assert svc.engine.search(users["finance"], GOC).results == [] or \
        "SF-002" not in [r.doc_id for r in svc.engine.search(users["finance"], GOC).results]
    _edit_acl(data_copy / "shared_folder" / "분석매뉴얼" / "GoC_단위_변동분석_매뉴얼.md",
              "allowed_groups: [actuarial, finance]")
    rep = svc.sync.sync()
    sf = next(s for s in rep.sources if s.source_key == "shared_folder")
    rec(f"acl_changed={sf.acl_changed}")
    assert sf.acl_changed == ["SF-002"] and not sf.updated
    assert "SF-002" in [r.doc_id for r in svc.engine.search(users["finance"], GOC).results]
    assert svc.engine.open_document(users["finance"], "SF-002") is not None


def test_acl_revoke_blocks_cache_and_history(svc, users, data_copy, rec):
    """입력조건: 재무팀이 접근 가능한 SF-001 로 검색·이력 생성 → SF-001 권한을 계리팀 전용으로 회수 → 색인 갱신
    예상결과: 같은 질문 재검색(캐시 포함)에서 SF-001 미노출, 원문 열람 불가, 이전 답변 이력은 숨김 처리"""
    q = "IFRS17 결산 검증 절차"
    fin = users["finance"]
    first = svc.engine.search(fin, q)
    assert "SF-001" in [r.doc_id for r in first.results]
    assert svc.engine.search(fin, q).from_cache is True  # 캐시가 실제로 동작함을 확인
    entry = HistoryEntry(fin.user_id, q, "local", "답변", [(r.doc_id, r.title, r.content_hash) for r in first.results])
    assert not revalidate_history([entry], fin, svc.indexer, svc.access)[0].hidden

    _edit_acl(data_copy / "shared_folder" / "결산검증" / "IFRS17_결산검증가이드.md", "allowed_groups: [actuarial]")
    svc.sync.sync()

    after = svc.engine.search(fin, q)
    rec(f"회수 후 재무팀 결과={[r.doc_id for r in after.results]}, from_cache={after.from_cache}")
    assert "SF-001" not in [r.doc_id for r in after.results] and not after.from_cache
    assert svc.engine.open_document(fin, "SF-001") is None
    shown = revalidate_history([entry], fin, svc.indexer, svc.access)
    assert shown[0].hidden and shown[0].source_titles == []


def test_cache_is_per_user(svc, users):
    """입력조건: 관리자가 검색(캐시 생성) 직후 같은 질문을 재무팀이 검색
    예상결과: 재무팀은 관리자 캐시를 재사용하지 못하고 권한 있는 문서만 받음"""
    q = "결산 검증 예외 승인 내역 모델 실행 오류"
    admin_ids = {r.doc_id for r in svc.engine.search(users["admin"], q).results}
    fin = svc.engine.search(users["finance"], q)
    assert not fin.from_cache
    assert {r.doc_id for r in fin.results} <= {"SF-001", "GW-002", "BS-002"}
    assert admin_ids - {"SF-001", "GW-002", "BS-002"}


def test_history_hidden_for_other_user(svc, users):
    """입력조건: 계리팀 사용자의 질문 이력을 재무팀 사용자 화면에서 조회
    예상결과: 다른 사용자의 이력은 표시되지 않음"""
    e = HistoryEntry("u_actuary", "q", "local", "a", [("GW-001", "t", "h")])
    assert revalidate_history([e], users["finance"], svc.indexer, svc.access) == []
