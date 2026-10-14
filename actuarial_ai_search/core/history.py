"""이전 질문·답변 내역과 권한/내용 재검증.

내역에는 답변 텍스트와 함께 근거 문서의 (doc_id, content_hash) 를 보관한다. 화면에 다시 보여줄 때마다
- 현재 사용자의 내역만 표시하고,
- 근거 문서가 삭제되었거나 / 현재 사용자의 권한이 회수되었거나 / 내용이 바뀌었으면
  답변과 출처를 숨기고 안내 문구로 대체한다. (권한이 회수된 문서 내용이 이전 답변으로 노출되지 않도록)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from core.access_control import AccessController, User
from core.indexer import Indexer

HIDDEN_NOTICE = ("이 답변의 근거 문서가 삭제·변경되었거나 접근권한이 변경되어 내용을 표시하지 않습니다. "
                 "필요하면 질문을 다시 검색해 주세요.")


@dataclass
class HistoryEntry:
    user_id: str
    query: str
    mode: str
    answer_text: str  # 화면 표시용 요약 (로컬 모드는 검색 결과 안내문)
    sources: list[tuple[str, str, str]] = field(default_factory=list)  # (doc_id, title, content_hash)
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass
class DisplayEntry:
    entry: HistoryEntry
    hidden: bool
    source_titles: list[str]


def revalidate_history(entries: list[HistoryEntry], user: User | None, indexer: Indexer,
                       access: AccessController) -> list[DisplayEntry]:
    shown: list[DisplayEntry] = []
    for e in entries:
        if user is None or e.user_id != user.user_id:
            continue
        ok = True
        for doc_id, _title, chash in e.sources:
            doc = indexer.get_document(doc_id)
            if doc is None or not access.can_access(user, doc) or indexer.content_hash_of(doc_id) != chash:
                ok = False
                break
        shown.append(DisplayEntry(e, hidden=not ok, source_titles=[t for _, t, _ in e.sources] if ok else []))
    return shown
