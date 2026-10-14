import json

from connectors.base import BaseConnector, ConnectorError
from core.models import FetchResult
from core.services import build_services

NEW_DOC = """---
doc_id: SF-100
title: 신규 사업비 가정 점검표
category: 기타
version: 1.0
created_at: 2026-10-10
modified_at: 2026-10-10
department: 계리평가팀
location: smb://fileserver.example.invalid/actuarial/가정관리/신규.md
allowed_users: []
allowed_groups: [actuarial]
---
# 신규 사업비 가정 점검표

사업비 가정 점검 시에는 유지비율과 신계약비율의 추이를 확인하고 이상치를 기록합니다.
"""


def _sf(data):
    return data / "shared_folder" / "계리평가"


def _result(rep, key):
    return next(s for s in rep.sources if s.source_key == key)


class BrokenConnector(BaseConnector):
    source_key, source_label = "groupware", "그룹웨어"

    def health_check(self):
        raise ConnectorError("연결 거부 (테스트)")

    def fetch_all(self) -> FetchResult:
        raise ConnectorError("연결 거부 (테스트)")


class CrashingConnector(BrokenConnector):
    def fetch_all(self):
        raise RuntimeError("민감한 내부 정보 SECRET-123")


def test_initial_sync_indexes_all(svc, rec):
    """입력조건: 최초 색인
    예상결과: 15건 색인(공유 9/그룹웨어 3/업무 3), 세 저장소 상태 ok"""
    assert svc.indexer.count_documents() == 15
    assert [s["status"] for s in svc.indexer.source_statuses()] == ["ok"] * 3
    rec("15건 색인, 3개 저장소 ok")


def test_resync_without_changes_is_noop(svc):
    """입력조건: 변경 없이 색인 갱신 재실행
    예상결과: 변경 0건, 중복 등록 없음(문서 수 15 유지), 색인 세대 번호 불변"""
    gen = svc.indexer.get_generation()
    rep = svc.sync.sync()
    assert not rep.changed and svc.indexer.count_documents() == 15
    assert svc.indexer.get_generation() == gen


def test_new_document_reflected(svc, users, data_copy, rec):
    """입력조건: 공유폴더에 신규 문서 추가 후 색인 갱신
    예상결과: 갱신 전 검색 불가 → 갱신 후 검색됨, 신규 1건 감지"""
    q = "신규 사업비 가정 점검표"
    assert "SF-100" not in [r.doc_id for r in svc.engine.search(users["actuary"], q).results]
    (_sf(data_copy) / "가정관리" / "신규.md").write_text(NEW_DOC, encoding="utf-8")
    rep = svc.sync.sync()
    assert _result(rep, "shared_folder").added == ["SF-100"]
    r = svc.engine.search(users["actuary"], q)
    rec(f"신규 반영 후 1위={r.results[0].doc_id}")
    assert r.results[0].doc_id == "SF-100"


def test_modified_document_reflected(svc, users, data_copy, rec):
    """입력조건: GW-002(공지) 본문 수정(마감일 변경) 후 색인 갱신
    예상결과: 수정 1건 감지, 최신 문구로 검색되고 이전 문구는 더 이상 검색되지 않음"""
    p = data_copy / "groupware" / "posts" / "GW-002.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert svc.engine.search(users["finance"], "재무제표 확정").results
    d["body"] = d["body"].replace("재무제표 확정", "재무제표 공시준비")
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    rep = svc.sync.sync()
    gw = _result(rep, "groupware")
    assert gw.updated == ["GW-002"] and not gw.version_changed
    new = svc.engine.search(users["finance"], "공시준비")
    rec(f"수정 후 검색 1위={new.results[0].doc_id if new.results else None}")
    assert new.results and new.results[0].doc_id == "GW-002"
    chunks = " ".join(c.text for c in svc.indexer.get_chunks("GW-002"))
    assert "공시준비" in chunks and "재무제표 확정" not in chunks


def test_version_change_detected(svc, data_copy):
    """입력조건: BS-003 버전 2.0 → 2.1 변경 후 색인 갱신
    예상결과: 버전변경으로 분류, 색인의 버전 값 갱신, 문서 중복 없음"""
    p = data_copy / "business_system" / "records" / "BS-003.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["version"] = "2.1"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    bs = _result(svc.sync.sync(), "business_system")
    assert bs.version_changed == ["BS-003"] and not bs.added
    assert svc.indexer.get_document("BS-003").version == "2.1" and svc.indexer.count_documents() == 15


def test_deleted_document_removed(svc, users, data_copy, rec):
    """입력조건: GW-001 게시글 삭제 후 색인 갱신
    예상결과: 삭제 1건 감지, 검색/원문 열람/색인 조각에서 모두 제거, 이전 캐시 결과도 제거"""
    q = "RAFM 모델 실행 오류 E101"
    assert svc.engine.search(users["actuary"], q).results[0].doc_id == "GW-001"
    (data_copy / "groupware" / "posts" / "GW-001.json").unlink()
    gw = _result(svc.sync.sync(), "groupware")
    r = svc.engine.search(users["actuary"], q)
    rec(f"삭제 후 결과={[x.doc_id for x in r.results]}")
    assert gw.deleted == ["GW-001"]
    assert "GW-001" not in [x.doc_id for x in r.results] and not r.from_cache
    assert svc.engine.open_document(users["actuary"], "GW-001") is None
    assert svc.indexer.get_chunks("GW-001") == []


def test_file_becomes_invalid_is_removed(svc, data_copy):
    """입력조건: 색인된 파일이 손상(메타데이터 삭제)된 뒤 색인 갱신
    예상결과: 오래된 내용이 남지 않도록 색인에서 제거, 형식 오류로 보고"""
    (_sf(data_copy) / "가정관리" / "계리적_가정_변경_관리_기준.md").write_text("깨진 내용", encoding="utf-8")
    sf = _result(svc.sync.sync(), "shared_folder")
    assert sf.deleted == ["SF-003"] and len(sf.invalid) == 1
    assert svc.indexer.get_document("SF-003") is None


def test_duplicate_id_across_sources(svc, data_copy, rec):
    """입력조건: 그룹웨어에 이미 공유폴더가 사용 중인 ID(SF-001)로 게시글 추가
    예상결과: 먼저 등록된 공유폴더 문서 유지, 그룹웨어 문서는 중복으로 제외(중복 등록 없음)"""
    p = data_copy / "groupware" / "posts" / "GW-001.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d.update(post_id="SF-001", title="가짜 문서")
    (data_copy / "groupware" / "posts" / "dup.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    gw = _result(svc.sync.sync(), "groupware")
    rec(f"중복={gw.duplicates}")
    assert gw.duplicates == ["SF-001"]
    assert svc.indexer.get_document("SF-001").source_key == "shared_folder"
    assert svc.indexer.get_document("SF-001").title != "가짜 문서"


def test_connector_failure_isolated_and_reported(data_copy, tmp_path, rec):
    """입력조건: 그룹웨어 Connector 가 연결 오류를 내는 상태에서 색인·검색
    예상결과: 다른 두 저장소는 정상 색인/검색, 그룹웨어는 error 로 표시되어 검색 제외, 결과에 '검색 못한 저장소'로 안내"""
    s = build_services(data_copy, tmp_path / "i.db")
    s.connectors[1] = BrokenConnector(data_copy / "groupware")
    s.sync.connectors = s.connectors
    rep = s.sync.sync()
    assert [r.status for r in rep.sources] == ["ok", "error", "ok"] and rep.failed_sources[0].source_label == "그룹웨어"
    r = s.engine.search(s.access.get_user("u_actuary"), "모델 실행 오류")
    rec(f"결과 저장소={sorted({x.source_system for x in r.results})}, 제외={r.unavailable_sources}")
    assert r.results and "그룹웨어" not in {x.source_system for x in r.results}
    assert r.unavailable_sources == ["그룹웨어"]


def test_connector_crash_message_not_leaked(data_copy, tmp_path):
    """입력조건: Connector 가 예기치 않은 예외(내부정보 포함)를 던짐
    예상결과: 앱은 중단되지 않고 오류 유형만 보고, 예외 메시지의 민감 문자열은 보고서에 없음"""
    s = build_services(data_copy, tmp_path / "i.db")
    s.connectors[1] = CrashingConnector(data_copy / "groupware")
    s.sync.connectors = s.connectors
    rep = s.sync.sync()
    gw = _result(rep, "groupware")
    assert gw.status == "error" and "SECRET-123" not in gw.error and "RuntimeError" in gw.error
    assert "SECRET-123" not in " ".join(rep.summary_lines())


def test_source_recovery(data_copy, tmp_path):
    """입력조건: 저장소 오류 후 복구되어 다시 색인 갱신
    예상결과: 상태가 ok 로 돌아오고 해당 저장소 문서가 다시 검색됨"""
    s = build_services(data_copy, tmp_path / "i.db")
    s.sync.sync()
    posts = data_copy / "groupware" / "posts"
    posts.rename(data_copy / "groupware" / "posts_off")
    assert _result(s.sync.sync(), "groupware").status == "error"
    u = s.access.get_user("u_actuary")
    assert "GW-001" not in [r.doc_id for r in s.engine.search(u, "RAFM 모델 실행 오류 FAQ").results]
    (data_copy / "groupware" / "posts_off").rename(posts)
    assert _result(s.sync.sync(), "groupware").status == "ok"
    assert "GW-001" in [r.doc_id for r in s.engine.search(u, "RAFM 모델 실행 오류 FAQ").results]


def test_all_sources_down(data_copy, tmp_path):
    """입력조건: 세 저장소 모두 접근 불가
    예상결과: 예외 없이 no_sources 안내, 모든 저장소가 '검색 못한 저장소'로 표시"""
    s = build_services(data_copy, tmp_path / "i.db")
    s.sync.sync()
    import shutil
    for sub in ("shared_folder", "groupware", "business_system"):
        shutil.rmtree(data_copy / sub)
    s.sync.sync()
    r = s.engine.search(s.access.get_user("u_admin"), "결산")
    assert r.status == "no_sources" and len(r.unavailable_sources) == 3
