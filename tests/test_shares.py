import json
import os

import pytest

from conftest import TOTAL_DOCS
from connectors.shared_folder import SharedFolderConnector
from core.services import build_services
from core.shares import ShareError, ShareRegistry, validate_unc
from helpers import write_sidecar

PDF_UNC = "\\\\fs-actu01.example.invalid\\계리평가\\결산검증\\결산_내부통제_점검보고서.pdf"


def _registry(data):
    return ShareRegistry(data / "metadata" / "shares.json", data / "shared_folder")


def _new_share_dir(data, name="신계약팀"):
    d = data / "shared_folder" / name
    d.mkdir()
    (d / "점검메모.md").write_text(
        "---\ndoc_id: SF-300\ntitle: 신계약 점검 메모\ncategory: 기타\nversion: 1.0\ncreated_at: 2026-10-10\n"
        "modified_at: 2026-10-11\ndepartment: 신계약팀\nallowed_users: []\nallowed_groups: [actuarial]\n---\n"
        "# 신계약 점검 메모\n\n신계약 데이터 마감 전에 확인할 항목을 정리한 가상의 메모입니다.\n", encoding="utf-8")
    return d


@pytest.mark.parametrize("path", ["\\\\fs01\\공유", "\\\\fs-01.example.invalid\\계리평가\\하위\\폴더", "\\\\10.0.0.5\\share",
                                  "  \\\\fs01\\공유\\  "])
def test_valid_unc(path):
    """입력조건: 올바른 UNC 경로(호스트명/IP/하위폴더/앞뒤 공백·끝 역슬래시)
    예상결과: 통과하고 정규화(공백·끝 역슬래시 제거)"""
    assert validate_unc(path).startswith("\\\\") and not validate_unc(path).endswith("\\")


@pytest.mark.parametrize("path", ["", "C:\\temp", "//fs01/share", "\\\\fs01", "\\\\fs01\\", "\\fs01\\share",
                                  "\\\\fs01\\공유\\..\\x<y", "\\\\fs 01\\공유", "\\\\\\share"])
def test_invalid_unc(path):
    """입력조건: 잘못된 UNC(드라이브 경로, 슬래시, 공유명 없음, 금지문자, 호스트 없음)
    예상결과: ShareError"""
    with pytest.raises(ShareError):
        validate_unc(path)


def test_unc_path_built_from_share_root(data_copy, rec):
    """입력조건: 등록부 기반 공유폴더 Connector 로 PDF 문서 수집
    예상결과: 원본 위치가 '공유 UNC 루트 + 하위 경로(역슬래시)' 형태의 UNC 경로"""
    docs = {d.doc_id: d for d in SharedFolderConnector(
        data_copy / "shared_folder", _registry(data_copy)).fetch_all().documents}
    rec(docs["SF-101"].location)
    assert docs["SF-101"].location == PDF_UNC
    assert docs["SF-101"].file_type == "pdf" and docs["SF-101"].file_name == "결산_내부통제_점검보고서.pdf"
    assert docs["SF-201"].location.startswith("\\\\fs-fin01.example.invalid\\재무공유\\")
    assert all(d.location.startswith("\\\\") for d in docs.values())


def test_multi_share_collects_all_and_labels(svc, rec):
    """입력조건: 등록된 공유 3곳(계리평가/재무팀/관리자 전용)
    예상결과: 공유별로 문서가 수집되고 share 표시명이 채워짐, 총 15건 색인"""
    by_share = {}
    for d in svc.indexer.list_documents():
        if d.source_key == "shared_folder":
            by_share.setdefault(d.share, []).append(d.doc_id)
    rec({k: len(v) for k, v in by_share.items()})
    assert {k: len(v) for k, v in by_share.items()} == {"계리평가 공유": 6, "재무팀 공유": 2, "관리자 전용": 1}
    assert svc.indexer.count_documents() == TOTAL_DOCS


def test_register_new_share_indexes_its_documents(svc, users, data_copy, rec):
    """입력조건: 새 가상 폴더를 UNC 경로로 등록한 뒤 색인 갱신
    예상결과: 새 공유의 문서가 검색되고 원본 위치가 새 UNC 경로, 같은 문서 ID 중복 등록 없음"""
    _new_share_dir(data_copy)
    reg = svc.shares
    assert "신계약팀" in reg.unregistered_dirs()
    reg.register("신계약팀 공유", "\\\\fs-new01.example.invalid\\신계약", "신계약팀")
    rep = svc.sync.sync()
    sf = next(s for s in rep.sources if s.source_key == "shared_folder")
    assert sf.added == ["SF-300"] and not sf.invalid
    r = svc.engine.search(users["actuary"], "신계약 점검 메모")
    assert r.results[0].doc_id == "SF-300"
    assert r.results[0].location == "\\\\fs-new01.example.invalid\\신계약\\점검메모.md"
    rec(r.results[0].location)
    assert svc.sync.sync().changed is False  # 재실행해도 중복 등록 없음


def test_unregister_and_disable_remove_documents(svc, users, data_copy):
    """입력조건: 공유 등록 해제 / 검색 사용 안 함 설정 후 색인 갱신
    예상결과: 해당 공유 문서가 삭제로 처리되어 검색에서 사라지고, 다시 켜면 복원됨"""
    q = "결산 일정 마감 체크"
    assert any(r.doc_id == "SF-201" for r in svc.engine.search(users["actuary"], q, top_k=20).results)
    svc.shares.set_enabled("재무팀 공유", False)
    rep = svc.sync.sync()
    assert sorted(next(s for s in rep.sources if s.source_key == "shared_folder").deleted) == ["SF-201", "SF-202"]
    assert all(r.doc_id != "SF-201" for r in svc.engine.search(users["actuary"], q, top_k=20).results)
    svc.shares.set_enabled("재무팀 공유", True)
    svc.sync.sync()
    assert any(r.doc_id == "SF-201" for r in svc.engine.search(users["actuary"], q, top_k=20).results)
    assert svc.shares.unregister("재무팀 공유") and not svc.shares.unregister("없는 공유")
    svc.sync.sync()
    assert svc.indexer.get_document("SF-201") is None


def test_register_validation_errors(data_copy):
    """입력조건: 빈 이름, 잘못된 UNC, 경로 탈출(../, 하위경로), 없는 폴더, 중복 이름/UNC/폴더
    예상결과: 모두 ShareError 로 거부되고 등록부는 변경되지 않음"""
    reg = _registry(data_copy)
    before = reg.path.read_text(encoding="utf-8")
    ok_unc = "\\\\fs-x.example.invalid\\x"
    _new_share_dir(data_copy)
    cases = [("", ok_unc, "신계약팀"), ("n", "C:\\x", "신계약팀"), ("n", ok_unc, "../계리평가"),
             ("n", ok_unc, "계리평가/결산검증"), ("n", ok_unc, "없는폴더"), ("n", ok_unc, "."), ("n" * 41, ok_unc, "신계약팀"),
             ("계리평가 공유", ok_unc, "신계약팀"), ("n", "\\\\FS-ACTU01.example.invalid\\계리평가", "신계약팀"),
             ("n", ok_unc, "계리평가")]
    for name, unc, d in cases:
        with pytest.raises(ShareError):
            reg.register(name, unc, d)
    assert reg.path.read_text(encoding="utf-8") == before


def test_missing_share_folder_isolated(data_copy, tmp_path):
    """입력조건: 등록된 공유 중 하나의 가상 폴더가 사라짐(경로 없음)
    예상결과: 그 공유만 '접근할 수 없습니다'로 보고되고 나머지 공유 문서는 정상 수집"""
    import shutil
    shutil.rmtree(data_copy / "shared_folder" / "재무공유")
    res = SharedFolderConnector(data_copy / "shared_folder", _registry(data_copy)).fetch_all()
    assert any(i.path == "재무팀 공유" and "접근할 수 없습니다" in i.reason for i in res.invalid)
    assert len(res.documents) == 7


def test_binary_without_or_with_bad_sidecar(data_copy):
    """입력조건: 메타데이터(.meta.json) 없는 PDF, 형식이 깨진 메타데이터, 손상된 xlsx
    예상결과: 각각 사유와 함께 invalid 로 보고되고 다른 문서는 계속 수집"""
    root = data_copy / "shared_folder" / "계리평가"
    (root / "메타없음.pdf").write_bytes(b"%PDF-1.4\n")
    (root / "깨진.xlsx").write_bytes(b"nope")
    write_sidecar(root / "깨진.xlsx", doc_id="SF-400", title="깨진")
    (root / "나쁜메타.pdf").write_bytes(b"%PDF-1.4\n")
    (root / "나쁜메타.pdf.meta.json").write_text("{bad", encoding="utf-8")
    res = SharedFolderConnector(data_copy / "shared_folder", _registry(data_copy)).fetch_all()
    reasons = {i.path.split("/")[-1]: i.reason for i in res.invalid}
    assert "메타데이터 파일(.meta.json)이 없습니다" == reasons["메타없음.pdf"]
    assert "형식 오류" in reasons["나쁜메타.pdf"] and "Office" in reasons["깨진.xlsx"]
    assert len(res.documents) == 9


def test_legacy_single_root_mode_still_works(data_copy):
    """입력조건: 등록부 없이 루트 폴더 하나로 만든 기존 방식 Connector
    예상결과: 하위 폴더 전체를 읽고 기본 UNC 표시명이 사용됨 (기존 공유폴더 연결 기능 유지)"""
    res = SharedFolderConnector(data_copy / "shared_folder").fetch_all()
    assert len(res.documents) == 9 and not res.invalid
    assert all(d.location.startswith("\\\\fileserver.example.invalid\\공유폴더\\") for d in res.documents)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="심볼릭 링크 미지원")
def test_symlink_outside_share_is_ignored(data_copy, tmp_path):
    """입력조건: 공유 폴더 안에 공유 밖 파일을 가리키는 심볼릭 링크
    예상결과: 공유 밖 파일은 읽지 않음(경로 탈출 방지)"""
    secret = tmp_path / "secret.md"
    secret.write_text("---\ndoc_id: X-1\ntitle: t\ncategory: 기타\nversion: 1\ncreated_at: 2026-01-01\n"
                      "modified_at: 2026-01-01\ndepartment: d\n---\n비밀 본문 내용입니다 충분히 길게 작성합니다.", encoding="utf-8")
    try:
        os.symlink(secret, data_copy / "shared_folder" / "계리평가" / "link.md")
    except OSError:
        pytest.skip("심볼릭 링크 생성 권한 없음")
    res = SharedFolderConnector(data_copy / "shared_folder", _registry(data_copy)).fetch_all()
    assert "X-1" not in {d.doc_id for d in res.documents}


def test_registry_file_roundtrip_keeps_notice(data_copy):
    """입력조건: 공유 등록 후 등록부 파일 확인
    예상결과: JSON 형식 유지, 안내(notice)문 보존, 한글 그대로 저장"""
    _new_share_dir(data_copy)
    reg = _registry(data_copy)
    reg.register("신계약팀 공유", "\\\\fs-new01.example.invalid\\신계약", "신계약팀")
    data = json.loads(reg.path.read_text(encoding="utf-8"))
    assert "실제 SMB" in data["notice"] and data["shares"][-1]["name"] == "신계약팀 공유"
