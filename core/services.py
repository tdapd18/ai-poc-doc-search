"""서비스 조립 (의존성 연결). app.py 와 테스트가 같은 방식으로 시스템을 구성한다."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from connectors.base import BaseConnector
from connectors.business_system import BusinessSystemConnector
from connectors.groupware import GroupwareConnector
from connectors.shared_folder import SharedFolderConnector
from core.access_control import AccessController, OSEnforcedAccessController
from core.app_config import AppConfig, ConfigError, ConfigStore
from core.config import PROJECT_ROOT
from core.fs import FileSystem, LocalFS
from core.identity import WindowsIdentity, current_identity
from core.answer_generator import AnswerGenerator
from core.indexer import IndexResetError, Indexer
from core.storage_security import StorageStatus, check_storage, purge_residue
from core.llm_client import LLMClient, build_client
from core.search_engine import SearchEngine
from core.shares import ShareRegistry
from core.sync_manager import SyncManager
from core.text_utils import SearchDictionary


@dataclass
class Services:
    data_dir: Path
    indexer: Indexer
    access: AccessController
    connectors: list[BaseConnector]
    sync: SyncManager
    engine: SearchEngine
    answers: AnswerGenerator
    shares: ShareRegistry | None = None
    config: AppConfig | None = None  # 실제 모드에서만
    config_store: ConfigStore | None = None
    identity: WindowsIdentity | None = None
    connector: object | None = None
    storage: StorageStatus | None = None  # 실제 모드: 로컬 색인 저장 위치 검증 결과
    notices: list[str] | None = None  # 시작 시 알림(예: 손상된 색인을 복구함)


class StorageBlockedError(RuntimeError):
    """로컬 색인 저장 위치의 보호를 확인하지 못해 색인 생성이 차단됨."""


def build_services(data_dir: Path | str, db_path: Path | str, llm: LLMClient | None = None,
                   llm_provider: str = "none", connectors: list[BaseConnector] | None = None) -> Services:
    data_dir = Path(data_dir)
    indexer = Indexer(db_path)
    access = AccessController.from_file(data_dir / "demo_users.json")
    dictionary = SearchDictionary.from_file(data_dir / "metadata" / "search_dictionary.json")
    shares_file = data_dir / "metadata" / "shares.json"
    registry = ShareRegistry(shares_file, data_dir / "shared_folder") if shares_file.is_file() else None
    connectors = connectors if connectors is not None else [
        SharedFolderConnector(data_dir / "shared_folder", registry),
        GroupwareConnector(data_dir / "groupware"),
        BusinessSystemConnector(data_dir / "business_system"),
    ]
    engine = SearchEngine(indexer, access, dictionary)
    return Services(
        data_dir=data_dir, indexer=indexer, access=access, connectors=connectors,
        sync=SyncManager(indexer, connectors), engine=engine,
        answers=AnswerGenerator(indexer, access, llm or build_client(llm_provider)), shares=registry,
    )


# ----------------------------------------------------------------------------- 실제 Windows 공유폴더 모드
def build_real_services(home: Path | str | None = None, *, fs: FileSystem | None = None,
                        identity: WindowsIdentity | None = None, data_dir: Path | str | None = None,
                        llm_provider: str = "none") -> Services:
    """개인 PC에서 실제 공유폴더를 검색하는 서비스 묶음.

    - 색인·설정·공유 등록·감사 로그는 모두 홈 폴더(계정별)에 둔다. 색인 소유 계정이 다르면 색인을 폐기한다.
    - 권한은 현재 Windows 계정의 실제 파일 접근 가능 여부(OSEnforcedAccessController)를 따른다.
    - ``fs`` 는 테스트용 주입(합성 Windows 공유). 운영에서는 None → OS 파일 API(LocalFS).
    """
    store = ConfigStore(home)
    cfg = store.load()
    cfg.mode = "real"
    identity = identity or current_identity()
    data_dir = Path(data_dir) if data_dir else PROJECT_ROOT / "data"
    status = check_storage(store.home)  # 권한을 바꾸지 않고 검증만 한다 (회사 보안정책 존중)
    purge_residue(store.home)  # 이전 실행·수동 복사로 남은 백업/임시/저널 파일을 덮어써 삭제
    notices: list[str] = []
    try:
        indexer = Indexer(store.home / "index.db")
        if indexer.recovered:
            notices.append("색인 파일이 손상되어 폐기하고 새로 만들었습니다. 원본 공유폴더 파일은 영향이 없습니다. 색인을 다시 생성하세요.")
            store.audit("index_recovered")
        indexer.ensure_owner(identity.key)
        if (store.home / RESET_MARKER).exists():  # 이전 색인 삭제가 끝나지 않은 채 종료됨 → 먼저 마무리
            indexer.reset()
            (store.home / RESET_MARKER).unlink(missing_ok=True)
    except (IndexResetError, sqlite3.DatabaseError, OSError):
        indexer = Indexer(":memory:")  # 안전한 임시 상태(디스크 색인 사용 불가) — 색인 생성·본문 노출 차단
        status = status.with_(index_ok=False, reasons=status.reasons + ("index_unrecoverable",),
                              messages=status.messages + ("기존 색인을 열거나 삭제하지 못해 색인 생성과 본문 표시를 차단했습니다. "
                                                         "설정 화면에서 색인 삭제를 다시 시도하거나 색인 폴더를 확인하세요.",))
    registry = ShareRegistry(store.home / "shares.json", store.home / "virtual")
    rules = data_dir / "metadata" / "category_rules.json"
    connector = SharedFolderConnector(store.home, registry, fs_factory=lambda share: fs or LocalFS(), config=cfg,
                                      rules=rules)
    access = OSEnforcedAccessController(identity, lambda doc: connector.fs_for_share_name(doc.share))
    dictionary = SearchDictionary.from_file(data_dir / "metadata" / "search_dictionary.json")
    engine = SearchEngine(indexer, access, dictionary)
    svc = Services(data_dir=data_dir, indexer=indexer, access=access, connectors=[connector],
                   sync=SyncManager(indexer, [connector]), engine=engine,
                   answers=AnswerGenerator(indexer, access, build_client(llm_provider)), shares=registry,
                   config=cfg, config_store=store, identity=identity, connector=connector, storage=status,
                   notices=notices)
    apply_storage_policy(svc)
    return svc


RESET_MARKER = "reset.pending"


def apply_storage_policy(svc: Services) -> None:
    """저장 위치 검증 결과를 검색 엔진과 설정(런타임)에 반영한다: 보호 미확인 → 본문 검색·표시 차단."""
    st = svc.storage
    if st is None:
        return
    svc.engine.body_blocked = not st.allow_body
    if svc.config is not None:
        svc.config._storage_blocked = not st.allow_full_text
    svc.engine.invalidate_cache()


def perform_index_reset(svc: Services) -> None:
    """색인을 모두 삭제한다. 실패해도 이전 본문이 노출되지 않도록 표시를 차단하고 IndexResetError 를 올린다(재시도 가능)."""
    assert svc.config_store is not None and svc.storage is not None
    marker = svc.config_store.home / RESET_MARKER
    marker.write_text("reset", encoding="utf-8")  # 도중에 종료돼도 다음 실행에서 마무리
    try:
        svc.indexer.reset()
    except IndexResetError:
        svc.storage = svc.storage.with_(index_ok=False, reasons=svc.storage.reasons + ("reset_failed",),
                                        messages=svc.storage.messages + ("색인 삭제에 실패했습니다. 이전 본문이 남아 있을 수 있어 본문 표시를 차단했습니다. 다시 시도하세요.",))
        apply_storage_policy(svc)
        raise
    marker.unlink(missing_ok=True)
    svc.storage = check_storage(svc.config_store.home)
    apply_storage_policy(svc)


def apply_index_mode(svc: Services, mode: str, *, approver: str = "", acknowledged: bool = False) -> bool:
    """색인 수준을 바꾼다. 바뀌면 기존 색인을 **모두 삭제**(본문이 남지 않도록 VACUUM)하고 True 를 반환한다.
    호출자는 이어서 색인을 다시 만들어야 한다."""
    assert svc.config is not None and svc.config_store is not None
    if mode == "full_text" and svc.storage is not None and not svc.storage.allow_full_text:
        raise ConfigError("로컬 색인 저장 위치가 안전하지 않아 본문 검색을 켤 수 없습니다. 설정 화면의 안내를 확인하세요.")
    changed = svc.config_store.set_index_mode(svc.config, mode, approver=approver, acknowledged=acknowledged)
    if changed:
        perform_index_reset(svc)  # 이전 본문이 남지 않도록 삭제 (실패 시 IndexResetError)
    return changed


def sync_with_audit(svc: Services, progress=None):
    """색인 갱신 + 감사 로그(건수만). 실제 모드에서 사용한다."""
    if svc.storage is not None and not svc.storage.allow_index:
        raise StorageBlockedError(" ".join(svc.storage.messages) or "로컬 색인 저장 위치를 확인하지 못해 색인 생성이 차단되었습니다.")
    report = svc.sync.sync(progress)
    if svc.config_store is not None:
        for s in report.sources:
            svc.config_store.audit("sync", status=s.status, added=len(s.added), updated=len(s.updated),
                                   deleted=len(s.deleted), unchanged=s.unchanged, denied=s.denied, retained=s.retained,
                                   invalid=len(s.invalid))
    return report
