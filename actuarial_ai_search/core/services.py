"""서비스 조립 (의존성 연결). app.py 와 테스트가 같은 방식으로 시스템을 구성한다."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from connectors.base import BaseConnector
from connectors.business_system import BusinessSystemConnector
from connectors.groupware import GroupwareConnector
from connectors.shared_folder import SharedFolderConnector
from core.access_control import AccessController
from core.answer_generator import AnswerGenerator
from core.indexer import Indexer
from core.llm_client import LLMClient, build_client
from core.search_engine import SearchEngine
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


def build_services(data_dir: Path | str, db_path: Path | str, llm: LLMClient | None = None,
                   llm_provider: str = "none", connectors: list[BaseConnector] | None = None) -> Services:
    data_dir = Path(data_dir)
    indexer = Indexer(db_path)
    access = AccessController.from_file(data_dir / "demo_users.json")
    dictionary = SearchDictionary.from_file(data_dir / "metadata" / "search_dictionary.json")
    connectors = connectors if connectors is not None else [
        SharedFolderConnector(data_dir / "shared_folder"),
        GroupwareConnector(data_dir / "groupware"),
        BusinessSystemConnector(data_dir / "business_system"),
    ]
    engine = SearchEngine(indexer, access, dictionary)
    return Services(
        data_dir=data_dir, indexer=indexer, access=access, connectors=connectors,
        sync=SyncManager(indexer, connectors), engine=engine,
        answers=AnswerGenerator(indexer, access, llm or build_client(llm_provider)),
    )
