"""저장소 Connector 공통 인터페이스.

실제 SMB / 사내 그룹웨어 API / 업무시스템 API 로 교체할 때에는 ``BaseConnector`` 를 상속한
새 구현체만 추가하면 된다. 검색 엔진·색인·권한 모듈은 이 인터페이스만 사용한다.

주의: 실제 시스템의 로그인 방식과 API 구조는 확인되지 않았으므로 이 PoC의 구현체는
가상 로컬 폴더(data/)만 읽으며, 인증/네트워크 코드를 포함하지 않는다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from core.models import Document, FetchResult, InvalidItem


class ConnectorError(Exception):
    """저장소 단위 오류(접속 불가, 루트 폴더 없음 등). 메시지에 민감정보를 넣지 않는다."""


class BaseConnector(ABC):
    source_key: str = ""  # 내부 식별자
    source_label: str = ""  # 화면 표시명

    def __init__(self, root: Path | str):
        self.root = Path(root)

    @abstractmethod
    def health_check(self) -> None:
        """저장소에 접근 가능한지 확인한다. 불가하면 ConnectorError."""

    @abstractmethod
    def fetch_all(self) -> FetchResult:
        """접근 가능한 모든 문서를 공통 ``Document`` 로 반환한다.

        - 저장소 전체 오류는 ConnectorError 로 올린다.
        - 개별 문서의 형식 오류는 예외 대신 ``FetchResult.invalid`` 에 기록하고 계속 진행한다.
        - 같은 저장소 안의 중복 문서 ID는 첫 번째만 채택하고 ``FetchResult.duplicates`` 에 기록한다.
        """

    # 공통 보조: 중복 ID 처리 -------------------------------------------------
    @staticmethod
    def _add_unique(result: FetchResult, doc: Document, origin: str) -> None:
        if any(d.doc_id == doc.doc_id for d in result.documents):
            result.duplicates.append(doc.doc_id)
            result.invalid.append(InvalidItem(origin, f"중복 문서 ID: {doc.doc_id} (먼저 읽은 문서만 사용)"))
            return
        result.documents.append(doc)
