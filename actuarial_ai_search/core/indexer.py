"""SQLite 기반 문서 색인 저장소.

테이블
- documents  : 문서 메타데이터 + 본문 + 접근권한 + 내용/권한 해시
- chunks     : 문단 단위 조각 (heading, text, 지시문 의심 플래그)
- source_status : 저장소별 마지막 동기화 상태 (ok / error)
- meta       : index_generation (색인이 바뀔 때마다 증가 → 검색 캐시 무효화 기준)

이 모듈은 접근권한을 판정하지 않는다(저장만). 판정은 항상 core.access_control 을 통해 호출 측에서 수행한다.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from core.document_parser import detect_injection, split_chunks
from core.models import Chunk, Document

SCHEMA_VERSION = "3"  # 색인은 원본에서 다시 만들 수 있는 파생 데이터이므로, 버전이 다르면 비우고 다시 만든다.

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY, title TEXT NOT NULL, source_key TEXT NOT NULL, source_system TEXT NOT NULL,
    category TEXT NOT NULL, version TEXT NOT NULL, created_at TEXT NOT NULL, modified_at TEXT NOT NULL,
    department TEXT NOT NULL, location TEXT NOT NULL, location_detail TEXT NOT NULL DEFAULT '',
    attachments_json TEXT NOT NULL DEFAULT '[]', allowed_users_json TEXT NOT NULL DEFAULT '[]',
    allowed_groups_json TEXT NOT NULL DEFAULT '[]', body TEXT NOT NULL,
    file_type TEXT NOT NULL DEFAULT 'md', file_name TEXT NOT NULL DEFAULT '', share TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL, acl_hash TEXT NOT NULL, indexed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    seq INTEGER NOT NULL, heading TEXT NOT NULL, text TEXT NOT NULL,
    flagged INTEGER NOT NULL DEFAULT 0, flag_reason TEXT NOT NULL DEFAULT '', loc TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE TABLE IF NOT EXISTS source_status (
    source_key TEXT PRIMARY KEY, source_label TEXT NOT NULL, status TEXT NOT NULL,
    last_sync_at TEXT NOT NULL, last_success_at TEXT NOT NULL DEFAULT '', message TEXT NOT NULL DEFAULT ''
);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Indexer:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._memory_conn = sqlite3.connect(":memory:") if str(self.db_path) == ":memory:" else None
        with self._conn() as c:
            self._migrate(c)
            c.executescript(_SCHEMA)
            c.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('index_generation', '0')")
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)", (SCHEMA_VERSION,))

    @staticmethod
    def _migrate(c: sqlite3.Connection) -> None:
        has_meta = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
        current = None
        if has_meta:
            row = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            current = row[0] if row else None
        if has_meta and current != SCHEMA_VERSION:
            for table in ("chunks", "documents", "source_status", "meta"):
                c.execute(f"DROP TABLE IF EXISTS {table}")

    @contextmanager
    def _conn(self):
        conn = self._memory_conn or sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if self._memory_conn is None:
                conn.close()

    # -- 세대(generation) ----------------------------------------------------
    def get_generation(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT value FROM meta WHERE key='index_generation'").fetchone()[0])

    @staticmethod
    def _bump(c: sqlite3.Connection) -> None:
        c.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key='index_generation'")

    # -- 동기화 지원 ---------------------------------------------------------
    def snapshot(self, source_key: str) -> dict[str, dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT doc_id, version, content_hash, acl_hash FROM documents WHERE source_key=?", (source_key,)
            ).fetchall()
        return {r["doc_id"]: dict(r) for r in rows}

    def owner_of(self, doc_id: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT source_key FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        return row["source_key"] if row else None

    def apply_changes(self, source_key: str, upserts: list[Document], deletes: list[str]) -> None:
        """한 저장소의 변경분을 단일 트랜잭션으로 반영한다 (중간 실패 시 전체 롤백)."""
        if not upserts and not deletes:
            return
        with self._conn() as c:
            for doc_id in deletes:
                c.execute("DELETE FROM documents WHERE doc_id=? AND source_key=?", (doc_id, source_key))
            for d in upserts:
                c.execute("DELETE FROM documents WHERE doc_id=?", (d.doc_id,))  # chunks 는 CASCADE
                c.execute(
                    "INSERT INTO documents (doc_id, title, source_key, source_system, category, version, created_at,"
                    " modified_at, department, location, location_detail, attachments_json, allowed_users_json,"
                    " allowed_groups_json, body, file_type, file_name, share, content_hash, acl_hash, indexed_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (d.doc_id, d.title, d.source_key, d.source_system, d.category, d.version, d.created_at,
                     d.modified_at, d.department, d.location, d.location_detail,
                     json.dumps(list(d.attachments), ensure_ascii=False),
                     json.dumps(list(d.allowed_users), ensure_ascii=False),
                     json.dumps(list(d.allowed_groups), ensure_ascii=False),
                     d.body, d.file_type, d.file_name, d.share, d.content_hash(), d.acl_hash(), _now()),
                )
                for seq, (heading, loc, text) in enumerate(self._segments(d)):
                    reason = detect_injection(text)
                    c.execute(
                        "INSERT INTO chunks(doc_id, seq, heading, text, flagged, flag_reason, loc) VALUES (?,?,?,?,?,?,?)",
                        (d.doc_id, seq, heading, text, int(bool(reason)), reason, loc),
                    )
            self._bump(c)

    @staticmethod
    def _segments(d: Document) -> list[tuple[str, str, str]]:
        """형식별 위치가 보존된 조각(segments)을 우선 사용하고, 없으면 본문을 문단으로 나눈다."""
        if d.segments:
            return [(h, loc or f"§ {h}", t) for h, loc, t in d.segments]
        return [(c.heading, c.loc or f"§ {c.heading}", c.text) for c in split_chunks(d.title, d.body)]

    def set_source_status(self, source_key: str, label: str, ok: bool, message: str = "") -> None:
        with self._conn() as c:
            prev = c.execute("SELECT status, last_success_at FROM source_status WHERE source_key=?",
                             (source_key,)).fetchone()
            now = _now()
            status = "ok" if ok else "error"
            last_ok = now if ok else (prev["last_success_at"] if prev else "")
            c.execute(
                "INSERT INTO source_status VALUES (?,?,?,?,?,?) ON CONFLICT(source_key) DO UPDATE SET "
                "source_label=excluded.source_label, status=excluded.status, last_sync_at=excluded.last_sync_at, "
                "last_success_at=excluded.last_success_at, message=excluded.message",
                (source_key, label, status, now, last_ok, message),
            )
            if prev is None or prev["status"] != status:
                self._bump(c)  # 검색 가능 저장소 구성이 바뀌었으므로 캐시 무효화

    def source_statuses(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM source_status ORDER BY source_key").fetchall()]

    # -- 조회 ----------------------------------------------------------------
    @staticmethod
    def _row_to_doc(r: sqlite3.Row) -> Document:
        return Document(
            doc_id=r["doc_id"], title=r["title"], source_key=r["source_key"], source_system=r["source_system"],
            category=r["category"], version=r["version"], created_at=r["created_at"], modified_at=r["modified_at"],
            department=r["department"], location=r["location"], body=r["body"],
            allowed_users=tuple(json.loads(r["allowed_users_json"])),
            allowed_groups=tuple(json.loads(r["allowed_groups_json"])),
            location_detail=r["location_detail"], attachments=tuple(json.loads(r["attachments_json"])),
            file_type=r["file_type"], file_name=r["file_name"], share=r["share"],
        )

    def get_document(self, doc_id: str) -> Document | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        return self._row_to_doc(row) if row else None

    def content_hash_of(self, doc_id: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT content_hash FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        return row["content_hash"] if row else None

    def list_documents(self, searchable_only: bool = True) -> list[Document]:
        """searchable_only=True 이면 마지막 동기화에 성공한(status=ok) 저장소의 문서만 반환한다."""
        sql = "SELECT d.* FROM documents d"
        if searchable_only:
            sql += " JOIN source_status s ON s.source_key = d.source_key AND s.status = 'ok'"
        sql += " ORDER BY d.source_key, d.doc_id"
        with self._conn() as c:
            return [self._row_to_doc(r) for r in c.execute(sql).fetchall()]

    def get_chunks(self, doc_id: str) -> list[Chunk]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM chunks WHERE doc_id=? ORDER BY seq", (doc_id,)).fetchall()
        return [Chunk(r["seq"], r["heading"], r["text"], bool(r["flagged"]), r["flag_reason"], r["loc"]) for r in rows]

    def count_documents(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
