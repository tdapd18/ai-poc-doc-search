import json

import pytest

from connectors.base import ConnectorError
from connectors.business_system import BusinessSystemConnector
from connectors.groupware import GroupwareConnector
from connectors.shared_folder import SharedFolderConnector
from core.shares import ShareRegistry

REQUIRED = ("doc_id", "title", "source_system", "category", "version", "created_at", "modified_at",
            "department", "location", "body")


def _sf(data):
    """운영과 같은 방식: 등록부에 등록된 공유들을 읽는 공유폴더 Connector."""
    return SharedFolderConnector(data / "shared_folder", ShareRegistry(data / "metadata" / "shares.json",
                                                                       data / "shared_folder"))


def _conns(data):
    return (_sf(data), GroupwareConnector(data / "groupware"),
            BusinessSystemConnector(data / "business_system"))


def test_three_connectors_collect_documents(data_copy, rec):
    """입력조건: 가상 저장소 3개(공유폴더/그룹웨어/업무시스템) 수집
    예상결과: 공유폴더 9(md/txt/pdf/xlsx/pptx), 그룹웨어 3, 업무시스템 3건 — 총 15건, 형식 오류 없음"""
    counts = {}
    for c in _conns(data_copy):
        r = c.fetch_all()
        counts[c.source_label] = len(r.documents)
        assert not r.invalid
    rec(str(counts))
    assert counts == {"공유폴더": 9, "그룹웨어": 3, "업무시스템": 3}


def test_common_schema_has_all_metadata(data_copy):
    """입력조건: 세 Connector 수집 결과
    예상결과: 모든 문서가 공통 메타데이터(ID/문서명/시스템/분류/버전/작성·수정일/부서/위치/본문)를 가짐"""
    for c in _conns(data_copy):
        for d in c.fetch_all().documents:
            for f in REQUIRED:
                assert getattr(d, f), f"{d.doc_id}:{f}"
            assert d.source_system == c.source_label
            assert d.allowed_users or d.allowed_groups  # ACL 이 명시되어 있어야 한다


def test_doc_ids_unique_across_sources(data_copy):
    """입력조건: 세 저장소 전체 문서
    예상결과: 문서 ID 중복 없음"""
    ids = [d.doc_id for c in _conns(data_copy) for d in c.fetch_all().documents]
    assert len(ids) == len(set(ids)) == 15


def test_shared_folder_recursion_and_change_detection(data_copy, rec):
    """입력조건: 하위 폴더 포함 공유폴더 스캔 후 파일 추가/수정/삭제
    예상결과: 하위 폴더 파일 탐색, 신규/변경/삭제 파일이 각각 감지됨"""
    c = _sf(data_copy)
    before = c.scan()
    assert any("/" in p for p in before)  # 하위 폴더 탐색
    assert all(e.size > 0 and e.mtime_ns > 0 and e.sha256 for e in before.values())
    root = data_copy / "shared_folder"
    (root / "계리평가" / "가정관리" / "새문서.txt").write_text("x", encoding="utf-8")
    target = root / "계리평가" / "분석매뉴얼" / "GoC_단위_변동분석_매뉴얼.md"
    target.write_text(target.read_text(encoding="utf-8") + "\n추가 문장", encoding="utf-8")
    (root / "계리평가" / "결산검증" / "IFRS17_결산검증가이드.md").unlink()
    ch = c.detect_changes(before, c.scan())
    rec(str(ch))
    assert ch["new"] == ["계리평가/가정관리/새문서.txt"]
    assert ch["changed"] == ["계리평가/분석매뉴얼/GoC_단위_변동분석_매뉴얼.md"]
    assert ch["removed"] == ["계리평가/결산검증/IFRS17_결산검증가이드.md"]


def test_groupware_keeps_url_and_attachments(data_copy):
    """입력조건: 그룹웨어 게시글 수집
    예상결과: 게시글 고유 ID(GW-xxx)와 가상 원본 URL, 첨부파일 정보를 보존"""
    docs = {d.doc_id: d for d in GroupwareConnector(data_copy / "groupware").fetch_all().documents}
    assert docs["GW-001"].location.startswith("https://groupware.example.invalid/")
    assert any("RAFM_오류코드표" in a for a in docs["GW-001"].attachments)
    assert "RAFM_오류코드표" in docs["GW-001"].body  # 첨부파일명도 검색 가능


def test_business_system_preserves_id_and_screen_path(data_copy):
    """입력조건: 업무시스템 레코드 수집
    예상결과: 업무시스템 ID(BS-xxx)와 원본 화면 위치 보존, 구조화 표가 텍스트 표로 변환됨"""
    docs = {d.doc_id: d for d in BusinessSystemConnector(data_copy / "business_system").fetch_all().documents}
    d = docs["BS-001"]
    assert "실행이력 조회" in d.location_detail and d.location.startswith("https://bizsys.example.invalid/")
    assert "| 실행ID |" in d.body and "E101" in d.body


def test_invalid_documents_are_reported_not_crashing(data_copy, rec):
    """입력조건: 잘못된 형식 문서 5종(메타데이터 없음/필수 누락/날짜 오류/깨진 JSON/비UTF-8)
    예상결과: 예외 없이 invalid 목록에 사유만 기록, 정상 문서는 계속 수집, 사유에 본문 내용이 없음"""
    root = data_copy / "shared_folder" / "계리평가"
    (root / "bad1.md").write_text("메타데이터 없는 문서 SECRET-BODY", encoding="utf-8")
    (root / "bad2.md").write_text("---\ndoc_id: SF-900\ntitle: 제목만\n---\n본문 SECRET-BODY", encoding="utf-8")
    (root / "bad3.md").write_bytes("---\ndoc_id: SF-901\n".encode() + b"\xff\xfe\x00bad")
    (data_copy / "groupware" / "posts" / "broken.json").write_text("{not json SECRET-BODY", encoding="utf-8")
    sf = _sf(data_copy).fetch_all()
    gw = GroupwareConnector(data_copy / "groupware").fetch_all()
    rec(f"공유폴더 invalid={[i.path for i in sf.invalid]}, 그룹웨어 invalid={[i.path for i in gw.invalid]}")
    assert len(sf.documents) == 9 and len(sf.invalid) == 3
    assert len(gw.documents) == 3 and [i.path for i in gw.invalid] == ["broken.json"]
    assert all("SECRET-BODY" not in i.reason for i in sf.invalid + gw.invalid)
    # 날짜 형식 오류
    p = root / "bad4.md"
    p.write_text(
        "---\ndoc_id: SF-902\ntitle: t\ncategory: 기타\nversion: 1\ncreated_at: 2026-13-45\nmodified_at: 2026-01-01\n"
        "department: d\nlocation: l\n---\n본문", encoding="utf-8")
    assert any("날짜" in i.reason for i in _sf(data_copy).fetch_all().invalid)


def test_duplicate_id_in_same_source(data_copy):
    """입력조건: 같은 문서 ID(SF-001)를 가진 두 번째 파일 추가
    예상결과: 하나만 채택하고 중복 목록/오류 항목에 기록"""
    root = data_copy / "shared_folder" / "계리평가"
    src = (root / "결산검증" / "IFRS17_결산검증가이드.md").read_text(encoding="utf-8")
    (root / "가정관리" / "복사본.md").write_text(src, encoding="utf-8")
    r = _sf(data_copy).fetch_all()
    assert [d.doc_id for d in r.documents].count("SF-001") == 1
    assert r.duplicates == ["SF-001"] and any("중복" in i.reason for i in r.invalid)


def test_missing_root_raises_connector_error(tmp_path):
    """입력조건: 존재하지 않는 저장소 경로
    예상결과: ConnectorError (저장소 단위 오류로 상위에서 격리 처리)"""
    for cls in (SharedFolderConnector, GroupwareConnector, BusinessSystemConnector):
        with pytest.raises(ConnectorError):
            cls(tmp_path / "없는경로").fetch_all()


def test_business_record_with_bad_table_is_invalid(data_copy):
    """입력조건: 표의 행 길이가 컬럼 수와 다른 업무시스템 레코드
    예상결과: 해당 레코드만 invalid, 나머지 정상"""
    p = data_copy / "business_system" / "records" / "BS-001.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["table"]["rows"][0] = ["짧은행"]
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r = BusinessSystemConnector(data_copy / "business_system").fetch_all()
    assert len(r.documents) == 2 and len(r.invalid) == 1
