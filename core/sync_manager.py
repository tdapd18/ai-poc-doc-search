"""문서 변경 감지와 색인 갱신 (수동 실행; 자동 스케줄러는 후속 과제).

저장소별로 다음을 수행한다.
1. Connector.fetch_all() 로 현재 문서 목록 수집 (실패하면 해당 저장소만 'error' 처리, 다른 저장소는 계속)
2. 색인 스냅샷과 비교해 신규 / 수정 / 버전 변경 / 권한 변경 / 삭제 분류 (문서 고유 ID 기준)
3. 변경분을 단일 트랜잭션으로 반영하고 index_generation 을 올려 검색 캐시를 무효화

정책
- 문서 ID 가 이미 다른 저장소에서 사용 중이면 먼저 등록된 문서를 유지하고 새 문서는 건너뛴다(중복 ID 경고).
- 이번 수집에서 보이지 않는 문서(삭제, 또는 형식 오류로 읽을 수 없게 된 문서)는 색인에서 제거한다.
  (stale 내용이 남아 권한 회수/삭제 후에도 노출되는 것을 막는 fail-closed 정책)
- 저장소 오류 시 그 저장소의 기존 색인은 보존하되 상태를 'error' 로 표시해 검색에서 제외한다.
- 로그에는 문서 ID/건수만 남기고 본문은 남기지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from connectors.base import BaseConnector, ConnectorError
from core.indexer import Indexer
from core.logging_utils import get_logger, log_event
from core.models import Document, InvalidItem

_log = get_logger()


@dataclass
class SourceSyncResult:
    source_key: str
    source_label: str
    status: str = "ok"  # ok | error
    error: str = ""
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)  # 본문/메타 수정 (버전 동일)
    version_changed: list[str] = field(default_factory=list)
    acl_changed: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    unchanged: int = 0
    invalid: list[InvalidItem] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.version_changed or self.acl_changed or self.deleted)


@dataclass
class SyncReport:
    sources: list[SourceSyncResult] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(s.changed for s in self.sources)

    @property
    def failed_sources(self) -> list[SourceSyncResult]:
        return [s for s in self.sources if s.status == "error"]

    def summary_lines(self) -> list[str]:
        lines = []
        for s in self.sources:
            if s.status == "error":
                lines.append(f"[{s.source_label}] 오류: {s.error}")
                continue
            parts = []
            for label, items in (("신규", s.added), ("수정", s.updated), ("버전변경", s.version_changed),
                                 ("권한변경", s.acl_changed), ("삭제", s.deleted)):
                if items:
                    parts.append(f"{label} {len(items)}건({', '.join(items)})")
            lines.append(f"[{s.source_label}] " + (", ".join(parts) if parts else "변경 없음")
                         + f" · 변경 없는 문서 {s.unchanged}건")
            if s.invalid:
                lines.append(f"  ⚠ 형식 오류/중복으로 제외 {len(s.invalid)}건: "
                             + "; ".join(f"{i.path} ({i.reason})" for i in s.invalid))
        return lines


class SyncManager:
    def __init__(self, indexer: Indexer, connectors: list[BaseConnector]):
        self.indexer = indexer
        self.connectors = connectors

    def sync(self) -> SyncReport:
        report = SyncReport()
        for conn in self.connectors:
            report.sources.append(self._sync_one(conn))
        log_event(_log, "sync", sources=len(report.sources), failed=len(report.failed_sources),
                  changed=report.changed)
        return report

    def _sync_one(self, conn: BaseConnector) -> SourceSyncResult:
        res = SourceSyncResult(conn.source_key, conn.source_label)
        try:
            fetched = conn.fetch_all()
        except ConnectorError as exc:
            return self._fail(conn, res, str(exc))
        except Exception as exc:  # 어떤 Connector 오류도 다른 저장소에 전파하지 않는다. 메시지 원문은 기록하지 않음.
            return self._fail(conn, res, f"저장소 처리 중 예기치 않은 오류 ({type(exc).__name__})")

        res.invalid = list(fetched.invalid)
        res.duplicates = list(fetched.duplicates)
        before = self.indexer.snapshot(conn.source_key)

        upserts: list[Document] = []
        current_ids: set[str] = set()
        for doc in fetched.documents:
            owner = self.indexer.owner_of(doc.doc_id)
            if owner and owner != conn.source_key:  # 다른 저장소가 이미 사용 중인 ID
                res.duplicates.append(doc.doc_id)
                res.invalid.append(InvalidItem(doc.doc_id, f"다른 저장소({owner})에 이미 등록된 문서 ID"))
                continue
            current_ids.add(doc.doc_id)
            prev = before.get(doc.doc_id)
            if prev is None:
                res.added.append(doc.doc_id)
            else:
                content_changed = prev["content_hash"] != doc.content_hash()
                acl_changed = prev["acl_hash"] != doc.acl_hash()
                if prev["version"] != doc.version:
                    res.version_changed.append(doc.doc_id)
                elif content_changed:
                    res.updated.append(doc.doc_id)
                if acl_changed:
                    res.acl_changed.append(doc.doc_id)
                if not (content_changed or acl_changed or prev["version"] != doc.version):
                    res.unchanged += 1
                    continue
            upserts.append(doc)

        res.deleted = sorted(set(before) - current_ids)
        try:
            self.indexer.apply_changes(conn.source_key, upserts, res.deleted)
        except Exception as exc:
            return self._fail(conn, res, f"색인 반영 실패 ({type(exc).__name__}) — 변경 사항은 반영되지 않았습니다")
        self.indexer.set_source_status(conn.source_key, conn.source_label, ok=True)
        return res

    def _fail(self, conn: BaseConnector, res: SourceSyncResult, message: str) -> SourceSyncResult:
        res.status, res.error = "error", message
        res.added, res.updated, res.version_changed, res.acl_changed, res.deleted = [], [], [], [], []
        self.indexer.set_source_status(conn.source_key, conn.source_label, ok=False, message=message)
        log_event(_log, "sync_source_failed", source=conn.source_key)
        return res
