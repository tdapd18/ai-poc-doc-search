"""사용자별 접근권한.

!! 교육용 PoC 주의 !!
- 여기서 다루는 사용자는 data/demo_users.json 의 **가상 사용자**이며, 화면의 사용자 전환은
  실제 회사 인증 시스템이 아니다.
- 실제 운영에서는 사내 SSO·AD 로 사용자를 식별하고, 각 원본 시스템(공유폴더/그룹웨어/업무시스템)의
  ACL 을 연동하여 권한을 판정해야 한다. (docs/DESIGN.md 참조)

판정 규칙 (기본 거부)
1. 알 수 없는 사용자 → 거부
2. role == "admin" → 전체 허용 (PoC 규칙)
3. 문서의 allowed_users 에 user_id 가 있거나, allowed_groups 와 사용자 groups 가 겹치면 허용
4. 그 외(ACL 이 비어 있는 경우 포함) → 거부
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from core.models import Document


@dataclass(frozen=True)
class User:
    user_id: str
    name: str
    department: str
    role: str
    groups: tuple[str, ...]


class AccessController:
    def __init__(self, users: list[User], notice: str = ""):
        self._users = {u.user_id: u for u in users}
        self.notice = notice

    @classmethod
    def from_file(cls, path: Path | str) -> "AccessController":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        users = [
            User(u["user_id"], u["name"], u.get("department", ""), u.get("role", "member"), tuple(u.get("groups", [])))
            for u in data.get("users", [])
        ]
        return cls(users, data.get("notice", ""))

    def users(self) -> list[User]:
        return list(self._users.values())

    def get_user(self, user_id: str | None) -> User | None:
        return self._users.get(user_id) if user_id else None

    def can_access(self, user: User | None, doc: Document) -> bool:
        if user is None or user.user_id not in self._users:
            return False
        if user.role == "admin":
            return True
        if user.user_id in doc.allowed_users:
            return True
        return bool(set(user.groups) & set(doc.allowed_groups))

    def filter_documents(self, user: User | None, docs: list[Document]) -> list[Document]:
        return [d for d in docs if self.can_access(user, d)]
