"""웹 시연판(정적 HTML) 생성기.

프로젝트의 가상 데이터(data/)와 사전·사용자 정의를 읽어 `tools/web_demo_template.html` 의 `__DATA__` 자리에 넣고
단일 HTML 파일을 만든다. 검색·점수·권한 규칙은 템플릿의 JS 가 Python 구현(core/search_engine.py)과 같은 규칙으로 재현한다.
  python tools/build_web_demo.py [출력경로]      (기본: web_demo/index.html, git 제외)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.document_parser import detect_injection  # noqa: E402
from core.indexer import Indexer  # noqa: E402
from core.search_engine import location_key  # noqa: E402
from core.services import build_services  # noqa: E402


def build(out: Path) -> int:
    svc = build_services(ROOT / "data", Path(tempfile.mkdtemp()) / "i.db")
    docs = []
    for conn in svc.connectors:
        for d in conn.fetch_all().documents:
            chunks = []
            for seq, (h, loc, t) in enumerate(Indexer._segments(d)):
                reason = detect_injection(t)
                chunks.append(dict(seq=seq, h=h, loc=loc, t=t, f=bool(reason), fr=reason))
            docs.append(dict(id=d.doc_id, title=d.title, fileName=d.file_name, type=d.file_type, src=d.source_key,
                             srcLabel=d.source_system, share=d.share, locKey=location_key(d), cat=d.category,
                             ver=d.version, created=d.created_at, mod=d.modified_at, dept=d.department, loc=d.location,
                             locDetail=d.location_detail, users=list(d.allowed_users), groups=list(d.allowed_groups),
                             chunks=chunks))
    users = json.loads((ROOT / "data" / "demo_users.json").read_text(encoding="utf-8"))["users"]
    dictionary = json.loads((ROOT / "data" / "metadata" / "search_dictionary.json").read_text(encoding="utf-8"))
    data = json.dumps(dict(docs=docs, dict=dictionary, users=users), ensure_ascii=False).replace("</", "<\\/")
    html = (ROOT / "tools" / "web_demo_template.html").read_text(encoding="utf-8").replace("__DATA__", data)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return len(docs)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "web_demo" / "index.html"
    print(f"{build(target)} documents -> {target}")
