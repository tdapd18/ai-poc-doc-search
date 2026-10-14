"""가상 그룹웨어 Connector (data/groupware/posts/*.json).

게시글 JSON 구조(가상):
  post_id, board, title, body, author, created_at, modified_at, version, department,
  category, url, attachments[{name, size}], allowed_users[], allowed_groups[]
실제 그룹웨어 API 규격은 확인되지 않았으므로 이 구조는 PoC용 가정이다.
"""
from __future__ import annotations

import json

from connectors.base import BaseConnector, ConnectorError
from core.document_parser import to_common_document
from core.models import FetchResult, InvalidDocumentError, InvalidItem


class GroupwareConnector(BaseConnector):
    source_key = "groupware"
    source_label = "그룹웨어"

    def _posts_dir(self):
        return self.root / "posts"

    def health_check(self) -> None:
        if not self._posts_dir().is_dir():
            raise ConnectorError("그룹웨어 게시판에 접근할 수 없습니다 (경로 없음)")

    def fetch_all(self) -> FetchResult:
        self.health_check()
        result = FetchResult()
        for path in sorted(self._posts_dir().glob("*.json")):
            name = path.name
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise InvalidDocumentError("게시글 JSON 최상위가 객체가 아닙니다")
                attachments = data.get("attachments") or []
                if not isinstance(attachments, list):
                    raise InvalidDocumentError("attachments 형식 오류")
                att_names = tuple(
                    f"{a.get('name', '?')} ({a.get('size', '?')})" if isinstance(a, dict) else str(a)
                    for a in attachments
                )
                body = str(data.get("body", ""))
                if att_names:  # 첨부파일명도 검색되도록 본문 끝에 목록화 (첨부 내용 자체는 수집하지 않음)
                    body += "\n\n## 첨부파일\n" + "\n".join(f"- {a}" for a in att_names)
                meta = {
                    "doc_id": data.get("post_id"),
                    "title": data.get("title"),
                    "category": data.get("category"),
                    "version": data.get("version"),
                    "created_at": data.get("created_at"),
                    "modified_at": data.get("modified_at"),
                    "department": data.get("department"),
                    "location": data.get("url"),
                    "file_type": "post",
                    "file_name": data.get("title"),
                    "location_detail": f"그룹웨어 / {data.get('board', '게시판')} / 작성자 {data.get('author', '-')}",
                    "allowed_users": data.get("allowed_users"),
                    "allowed_groups": data.get("allowed_groups"),
                    "attachments": list(att_names),
                }
                doc = to_common_document(meta, body, source_key=self.source_key, source_system=self.source_label)
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
