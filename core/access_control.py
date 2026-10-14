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
from typing import Callable

from core.fs import FileSystem, FsError
from core.identity import WindowsIdentity
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

    def verify(self, user: User | None, doc: Document) -> bool:
        """사용자에게 **보여주기 직전**의 엄격한 재검증. 데모 ACL 방식에서는 can_access 와 같다."""
        return self.can_access(user, doc)

    def is_stale(self, doc: Document) -> bool:
        """색인 이후 원본이 바뀌었는지(데모 방식은 항상 False)."""
        return False


class OSEnforcedAccessController(AccessController):
    """실제 Windows 모드: **운영 체제가 현재 로그인 계정으로 판정**한 접근 가능 여부를 따른다.

    - 앱은 ACL 을 해석·복제하지 않는다. 파일을 실제로 열 수 있는지(``FileSystem.check_open``)가 권한의 근거다.
      (``os.access`` 는 Windows 에서 ACL 을 반영하지 않으므로 사용하지 않는다.)
    - ``can_access``  : 대량 필터용. 색인은 *색인 시점에 이 계정이 읽을 수 있었던* 파일만 담고 있으므로 신원만 확인한다(OS 호출 없음).
    - ``verify``      : 결과 행·미리보기·AI 근거·이전 답변·캐시 적중처럼 **사용자에게 보이기 직전**마다 파일을 열어 확인한다.
                        삭제·권한 회수·공유 불가·잠금·확인 불가는 모두 거부(fail-closed)한다.
    - ``is_stale``    : 색인 이후 파일이 바뀌었는지(크기·수정시각 지문 비교) — 권한 문제는 아니므로 표시만 한다.
    """

    def __init__(self, identity: WindowsIdentity, fs_for: Callable[[Document], FileSystem]):
        self.identity = identity
        self._fs_for = fs_for
        self._user = User(identity.principal, identity.principal, "", "member", ())
        super().__init__([self._user], notice="실제 Windows 로그인 계정의 파일 접근권한이 적용됩니다.")

    def current_user(self) -> User:
        return self._user

    def can_access(self, user: User | None, doc: Document) -> bool:
        return user is not None and user.user_id.casefold() == self.identity.key

    def verify(self, user: User | None, doc: Document) -> bool:
        if not self.can_access(user, doc):
            return False
        try:
            self._fs_for(doc).check_open(doc.location)
            return True
        except FsError:
            return False
        except Exception:  # 어떤 예외도 "허용"으로 해석하지 않는다
            return False

    def is_stale(self, doc: Document) -> bool:
        if not doc.fingerprint:
            return False
        try:
            return self._fs_for(doc).stat(doc.location).fingerprint != doc.fingerprint
        except Exception:
            return False
