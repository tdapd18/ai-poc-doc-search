"""가상 업무시스템 Connector (data/business_system/records/*.json).

레코드 JSON 구조(가상):
  record_id, record_type, title, category, version, created_at, modified_at, department,
  screen_path(원본 화면 경로), url, summary, table{columns, rows}, sections[{heading, text}],
  allowed_users[], allowed_groups[]
업무시스템의 구조화 데이터(표/항목)를 검색 가능한 텍스트(마크다운)로 변환한다.
실제 업무시스템 API/DB 규격은 확인되지 않았으므로 추측 구현하지 않았다.
"""
from __future__ import annotations

import json

from connectors.base import BaseConnector, ConnectorError
from core.document_parser import to_common_document
from core.models import FetchResult, InvalidDocumentError, InvalidItem


def _render_body(data: dict) -> str:
    parts: list[str] = []
    if data.get("summary"):
        parts.append(str(data["summary"]))
    for sec in data.get("sections") or []:
        if not isinstance(sec, dict):
            raise InvalidDocumentError("sections 형식 오류")
        parts.append(f"## {sec.get('heading', '')}\n\n{sec.get('text', '')}")
    table = data.get("table")
    if table:
        if not isinstance(table, dict) or not isinstance(table.get("columns"), list) \
                or not isinstance(table.get("rows"), list):
            raise InvalidDocumentError("table 형식 오류")
        cols = [str(c) for c in table["columns"]]
        lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for row in table["rows"]:
            if not isinstance(row, list) or len(row) != len(cols):
                raise InvalidDocumentError("table 행 길이가 컬럼 수와 다릅니다")
            lines.append("| " + " | ".join(str(c) for c in row) + " |")
        title = table.get("title", "")
        parts.append((f"## {title}\n\n" if title else "") + "\n".join(lines))
    return "\n\n".join(parts)


class BusinessSystemConnector(BaseConnector):
    source_key = "business_system"
    source_label = "업무시스템"

    def _records_dir(self):
        return self.root / "records"

    def health_check(self) -> None:
        if not self._records_dir().is_dir():
            raise ConnectorError("업무시스템에 접근할 수 없습니다 (경로 없음)")

    def fetch_all(self) -> FetchResult:
        self.health_check()
        result = FetchResult()
        for path in sorted(self._records_dir().glob("*.json")):
            name = path.name
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise InvalidDocumentError("레코드 JSON 최상위가 객체가 아닙니다")
                meta = {
                    "doc_id": data.get("record_id"),
                    "title": data.get("title"),
                    "category": data.get("category"),
                    "version": data.get("version"),
                    "created_at": data.get("created_at"),
                    "modified_at": data.get("modified_at"),
                    "department": data.get("department"),
                    "location": data.get("url"),
                    "location_detail": f"업무시스템 화면: {data.get('screen_path', '-')} "
                                       f"(유형: {data.get('record_type', '-')})",
                    "allowed_users": data.get("allowed_users"),
                    "allowed_groups": data.get("allowed_groups"),
                }
                doc = to_common_document(
                    meta, _render_body(data), source_key=self.source_key, source_system=self.source_label
                )
            except json.JSONDecodeError:
                result.invalid.append(InvalidItem(name, "JSON 형식 오류"))
                continue
            except InvalidDocumentError as exc:
                result.invalid.append(InvalidItem(name, str(exc)))
                continue
            except (UnicodeDecodeError, OSError):
                result.invalid.append(InvalidItem(name, "파일을 읽을 수 없습니다"))
                continue
            self._add_unique(result, doc, name)
        return result
