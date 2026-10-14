"""현재 Windows 로그인 계정 식별.

앱은 사용자 PC 에서 그 사용자 계정으로 실행되므로, 파일 접근권한은 운영 체제가 이 계정을 기준으로 판정한다.
앱은 계정의 비밀번호·토큰을 다루지 않으며, 여기서는 표시와 색인 소유자 구분을 위한 이름만 읽는다.
"""
from __future__ import annotations

import getpass
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WindowsIdentity:
    domain: str
    username: str

    @property
    def principal(self) -> str:
        return f"{self.domain}\\{self.username}"

    @property
    def key(self) -> str:
        """비교용 키(Windows 계정명은 대소문자를 구분하지 않는다)."""
        return self.principal.casefold()


def current_identity(env: dict | None = None) -> WindowsIdentity:
    env = os.environ if env is None else env
    user = env.get("USERNAME") or env.get("USER")
    if not user:
        try:
            user = getpass.getuser()
        except Exception:  # 계정명을 알 수 없는 환경 — 임의 계정으로 가장하지 않는다
            user = "UNKNOWN"
    domain = env.get("USERDOMAIN") or env.get("COMPUTERNAME") or env.get("HOSTNAME") or "LOCAL"
    return WindowsIdentity(domain, user)
