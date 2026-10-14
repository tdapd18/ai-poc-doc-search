"""서비스 조립 (의존성 연결). app.py 와 테스트가 같은 방식으로 시스템을 구성한다."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from connectors.base import BaseConnector
from connectors.business_system import BusinessSystemConnector
from connectors.groupware import GroupwareConnector
from connectors.shared_folder import SharedFolderConnector
from core.access_control import AccessController, OSEnforcedAccessController
from core.app_config import AppConfig, ConfigStore
from core.config import PROJECT_ROOT
from core.fs import FileSystem, LocalFS
from core.identity import WindowsIdentity, current_identity
from core.answer_generator import AnswerGenerator
from core.storage_security import harden_dir, purge_residue
from core.indexer import Indexer
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
    harden_dir(store.home)  # 색인 폴더: 현재 계정 전용
    purge_residue(store.home)  # 이전 실행·수동 복사로 남은 백업/임시/저널 파일을 덮어써 삭제
    indexer = Indexer(store.home / "index.db")
    indexer.ensure_owner(identity.key)
    registry = ShareRegistry(store.home / "shares.json", store.home / "virtual")
    rules = data_dir / "metadata" / "category_rules.json"
    connector = SharedFolderConnector(store.home, registry, fs_factory=lambda share: fs or LocalFS(), config=cfg,
                                      rules=rules)
    access = OSEnforcedAccessController(identity, lambda doc: connector.fs_for_share_name(doc.share))
    dictionary = SearchDictionary.from_file(data_dir / "metadata" / "search_dictionary.json")
    engine = SearchEngine(indexer, access, dictionary)
    return Services(data_dir=data_dir, indexer=indexer, access=access, connectors=[connector],
                    sync=SyncManager(indexer, [connector]), engine=engine,
                    answers=AnswerGenerator(indexer, access, build_client(llm_provider)), shares=registry,
                    config=cfg, config_store=store, identity=identity, connector=connector)


def apply_index_mode(svc: Services, mode: str, *, approver: str = "", acknowledged: bool = False) -> bool:
    """색인 수준을 바꾼다. 바뀌면 기존 색인을 **모두 삭제**(본문이 남지 않도록 VACUUM)하고 True 를 반환한다.
    호출자는 이어서 색인을 다시 만들어야 한다."""
    assert svc.config is not None and svc.config_store is not None
    changed = svc.config_store.set_index_mode(svc.config, mode, approver=approver, acknowledged=acknowledged)
    if changed:
        svc.indexer.reset()
        svc.engine.invalidate_cache()
    return changed


def sync_with_audit(svc: Services, progress=None):
    """색인 갱신 + 감사 로그(건수만). 실제 모드에서 사용한다."""
    report = svc.sync.sync(progress)
    if svc.config_store is not None:
        for s in report.sources:
            svc.config_store.audit("sync", status=s.status, added=len(s.added), updated=len(s.updated),
                                   deleted=len(s.deleted), unchanged=s.unchanged, denied=s.denied, retained=s.retained,
                                   invalid=len(s.invalid))
    return report
