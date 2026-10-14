import errno
import json
import os

import pytest

from core.app_config import APPROVAL_STATEMENT, AppConfig, ConfigError, ConfigStore
from core.fs import (FsAccessDenied, FsNotFound, FsUnavailable, LocalFS, MappedFS, classify_oserror, normalize_unc,
                     to_extended_path, unc_join, unc_key, unc_parent, unc_relative)
from core.identity import current_identity

ROOT = "\\\\fs01.example.invalid\\공유"


@pytest.fixture
def share(tmp_path):
    (tmp_path / "Docs" / "하위 폴더").mkdir(parents=True)
    (tmp_path / "Docs" / "하위 폴더" / "보고서.TXT").write_text("내용", encoding="utf-8")
    (tmp_path / "Docs" / "a.txt").write_text("a", encoding="utf-8")
    return MappedFS({ROOT: tmp_path}), tmp_path


def test_unc_string_helpers(rec):
    """입력조건: UNC 문자열 정규화/결합/상대경로/상위/키/확장 경로 변환
    예상결과: 중복·끝 구분자 정리, 대소문자 무시 비교, 루트 밖 상대화 거부, 긴 경로 접두사 변환"""
    assert normalize_unc("\\\\srv\\\\sh\\\\a\\") == "\\\\srv\\sh\\a"
    assert unc_join("\\\\srv\\sh", "a", "b.txt") == "\\\\srv\\sh\\a\\b.txt"
    assert unc_relative("\\\\SRV\\Sh", "\\\\srv\\sh\\A\\b.txt") == "A\\b.txt"
    with pytest.raises(ValueError):
        unc_relative("\\\\srv\\sh", "\\\\srv\\sh2\\x")  # 접두사만 같은 다른 공유
    assert unc_parent("\\\\srv\\sh\\a\\b.txt") == "\\\\srv\\sh\\a"
    assert unc_key("\\\\SRV\\Sh\\A") == unc_key("\\\\srv\\sh\\a")
    assert to_extended_path("\\\\srv\\sh\\x") == "\\\\?\\UNC\\srv\\sh\\x"
    assert to_extended_path("C:\\x") == "\\\\?\\C:\\x" and to_extended_path("\\\\?\\UNC\\a\\b") == "\\\\?\\UNC\\a\\b"
    rec(to_extended_path("\\\\srv\\sh\\x"))


def test_mapped_fs_is_case_insensitive_like_windows(share):
    """입력조건: 대소문자가 다른 경로 / 한글·공백 폴더로 목록·상태·읽기
    예상결과: Windows 처럼 대소문자와 무관하게 같은 파일을 찾음"""
    fs, _ = share
    assert fs.read_bytes(ROOT + "\\docs\\하위 폴더\\보고서.txt", 100).decode() == "내용"
    names = {e.name for e in fs.scandir(ROOT + "\\DOCS")}
    assert names == {"하위 폴더", "a.txt"}
    assert fs.stat(ROOT + "\\Docs\\A.TXT").size == 1


def test_access_denied_semantics(share, rec):
    """입력조건: 폴더 목록 거부 / 파일 읽기 거부 주입
    예상결과: 목록 거부는 scandir 실패, 읽기 거부는 목록에는 보이나 열기·읽기는 FsAccessDenied (NTFS 에서 흔한 상태)"""
    fs, _ = share
    fs.deny_read(ROOT + "\\Docs\\a.txt")
    assert any(e.name == "a.txt" for e in fs.scandir(ROOT + "\\Docs"))
    for op in (lambda: fs.check_open(ROOT + "\\Docs\\a.txt"), lambda: fs.read_bytes(ROOT + "\\Docs\\a.txt", 10)):
        with pytest.raises(FsAccessDenied):
            op()
    fs.deny_list(ROOT + "\\Docs\\하위 폴더")
    with pytest.raises(FsAccessDenied):
        fs.scandir(ROOT + "\\Docs\\하위 폴더")
    with pytest.raises(FsAccessDenied):
        fs.read_bytes(ROOT + "\\Docs\\하위 폴더\\보고서.txt", 10)
    fs.allow(ROOT + "\\Docs\\a.txt")
    fs.check_open(ROOT + "\\Docs\\a.txt")
    rec("목록 거부/읽기 거부/복구 확인")


def test_offline_lock_vanish_and_not_found(share):
    """입력조건: 공유 오프라인 / 파일 잠금 / 목록 후 사라짐 / 없는 경로·루트 밖 경로·`..`
    예상결과: 각각 FsUnavailable / FsUnavailable / FsNotFound / FsNotFound"""
    fs, _ = share
    fs.lock(ROOT + "\\Docs\\a.txt")
    with pytest.raises(FsUnavailable):
        fs.read_bytes(ROOT + "\\Docs\\a.txt", 10)
    fs.lock(ROOT + "\\Docs\\a.txt", False)
    fs.vanish(ROOT + "\\Docs\\a.txt")
    with pytest.raises(FsNotFound):
        fs.check_open(ROOT + "\\Docs\\a.txt")
    for bad in (ROOT + "\\Docs\\없음.txt", "\\\\other\\share\\x", ROOT + "\\Docs\\..\\..\\etc"):
        with pytest.raises(FsNotFound):
            fs.stat(bad)
    fs.offline(ROOT)
    for op in (lambda: fs.scandir(ROOT), lambda: fs.stat(ROOT + "\\Docs\\a.txt")):
        with pytest.raises(FsUnavailable):
            op()
    fs.offline(ROOT, False)
    assert fs.scandir(ROOT)


def test_counters_distinguish_open_check_from_body_read(share):
    """입력조건: check_open 과 read_bytes 호출
    예상결과: opens 와 reads 가 따로 기록되어 '내용을 읽었는지'를 검증할 수 있음"""
    fs, _ = share
    fs.check_open(ROOT + "\\Docs\\a.txt")
    assert fs.opens and not fs.reads
    fs.read_bytes(ROOT + "\\Docs\\a.txt", 10)
    assert len(fs.reads) == 1


def test_symlink_reported_as_link(share, tmp_path):
    """입력조건: 폴더를 가리키는 링크(접합 점 모사)
    예상결과: is_link=True, 디렉터리로 취급하지 않음(순회 루프 방지의 근거)"""
    fs, base = share
    try:
        os.symlink(base / "Docs", base / "loop")
    except OSError:
        pytest.skip("심볼릭 링크 불가")
    e = next(x for x in fs.scandir(ROOT) if x.name == "loop")
    assert e.is_link and not e.is_dir


def test_oserror_classification(rec):
    """입력조건: Windows winerror(5,2,32,53,1231)와 errno 값
    예상결과: 거부 / 없음 / 사용 중(불가) / 네트워크(불가) 로 분류, 메시지에 경로 없음"""
    def mk(winerror=None, err=None):
        e = OSError(err or 0, "x")
        if winerror is not None:
            e.winerror = winerror
        return e
    assert isinstance(classify_oserror(mk(5)), FsAccessDenied)
    assert isinstance(classify_oserror(mk(2)), FsNotFound) and isinstance(classify_oserror(mk(3)), FsNotFound)
    assert isinstance(classify_oserror(mk(32)), FsUnavailable) and isinstance(classify_oserror(mk(53)), FsUnavailable)
    assert isinstance(classify_oserror(mk(1231)), FsUnavailable)
    assert isinstance(classify_oserror(OSError(errno.EACCES, "x")), FsAccessDenied)
    assert isinstance(classify_oserror(PermissionError()), FsAccessDenied)
    assert isinstance(classify_oserror(OSError(errno.ENOENT, "x")), FsNotFound)
    rec("winerror/errno 분류 확인")


def test_local_fs_on_plain_paths(tmp_path):
    """입력조건: LocalFS(OS 직접)로 로컬 폴더 읽기 / 없는 경로
    예상결과: 목록·상태·읽기·열기 확인 동작, 없는 경로는 FsNotFound (확장 경로 변환은 Windows 에서만 사용)"""
    (tmp_path / "x.txt").write_text("hello", encoding="utf-8")
    fs = LocalFS(extended_paths=False)
    p = str(tmp_path)
    assert [e.name for e in fs.scandir(p)] == ["x.txt"]
    assert fs.read_bytes(p + "/x.txt", 100) == b"hello" and fs.stat(p + "/x.txt").size == 5
    fs.check_open(p + "/x.txt")
    with pytest.raises(FsNotFound):
        fs.read_bytes(p + "/nope.txt", 10)
    assert fs.exists_dir(p) and not fs.exists_dir(p + "/nope")


# ---- 신원 / 설정 -------------------------------------------------------------
def test_identity_from_env():
    """입력조건: USERDOMAIN/USERNAME 환경값, 값이 없는 환경
    예상결과: 'DOMAIN\\user' 형태, 비교키는 대소문자 무시, 계정을 알 수 없으면 UNKNOWN (임의 계정 가장 금지)"""
    i = current_identity({"USERDOMAIN": "CORP", "USERNAME": "Hong"})
    assert i.principal == "CORP\\Hong" and i.key == "corp\\hong"
    assert current_identity({}).domain


def test_config_defaults_are_safe_and_roundtrip(tmp_path):
    """입력조건: 설정 파일이 없을 때 / 저장 후 재로드
    예상결과: 기본은 데모 모드·메타데이터 전용·승인 없음, 저장 값 보존, 파일 권한 600(posix)"""
    store = ConfigStore(tmp_path)
    cfg = store.load()
    assert (cfg.mode, cfg.index_mode, cfg.approval.approved, cfg.full_text) == ("demo", "metadata_only", False, False)
    cfg.mode, cfg.max_file_mb = "real", 5
    store.save(cfg)
    again = store.load()
    assert again.mode == "real" and again.max_file_mb == 5
    if os.name == "posix":
        assert oct(store.path.stat().st_mode)[-3:] == "600"


def test_full_text_requires_approval_record(tmp_path, rec):
    """입력조건: 승인 확인 없이/승인자 없이 본문 모드 전환 시도, 정상 승인 후 전환, 다시 메타 전용
    예상결과: 승인 없으면 ConfigError, 승인 시 기록(승인자·일시·문구) 저장, 메타 전용으로 돌아가면 승인 해제, 모드 변경은 True 반환(색인 초기화 신호)"""
    store = ConfigStore(tmp_path)
    cfg = store.load()
    with pytest.raises(ConfigError):
        store.set_index_mode(cfg, "full_text")
    with pytest.raises(ConfigError):
        store.set_index_mode(cfg, "full_text", approver="  ", acknowledged=True)
    with pytest.raises(ConfigError):
        store.set_index_mode(cfg, "full_text", approver="SEC-001", acknowledged=False)
    assert cfg.index_mode == "metadata_only"
    assert store.set_index_mode(cfg, "full_text", approver="SEC-001", acknowledged=True) is True
    loaded = store.load()
    assert loaded.full_text and loaded.approval.approver == "SEC-001" and loaded.approval.statement == APPROVAL_STATEMENT
    assert store.set_index_mode(loaded, "full_text", approver="SEC-001", acknowledged=True) is False  # 변화 없음
    assert store.set_index_mode(loaded, "metadata_only") is True
    assert not store.load().approval.approved
    rec("승인 기록 필수, 해제 시 승인도 해제")


def test_tampered_config_cannot_enable_full_text_without_record(tmp_path):
    """입력조건: 설정 파일에 index_mode=full_text 만 직접 써넣고 승인 기록은 없음
    예상결과: 로드 시 안전한 기본값(metadata_only)으로 되돌림"""
    (tmp_path / "config.json").write_text(json.dumps({"index_mode": "full_text"}), encoding="utf-8")
    assert ConfigStore(tmp_path).load().index_mode == "metadata_only"
    (tmp_path / "config.json").write_text("{깨진 json", encoding="utf-8")
    assert ConfigStore(tmp_path).load() == AppConfig()


def test_audit_log_has_no_paths_or_content(tmp_path):
    """입력조건: 경로 문자열·긴 문자열이 포함된 감사 이벤트 기록
    예상결과: 경로 구분자가 든 값은 기록하지 않고 긴 문자열은 잘라서 기록, 건수/상태는 기록"""
    store = ConfigStore(tmp_path)
    store.audit("sync", added=3, path="\\\\srv\\sh\\비밀.docx", note="x" * 200, url="a/b")
    line = store.audit_path.read_text(encoding="utf-8")
    assert '"added": 3' in line and "비밀" not in line and "a/b" not in line and "x" * 81 not in line
