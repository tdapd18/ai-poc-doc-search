"""공유폴더(UNC) 등록부.

FileLocator 류 도구처럼 여러 공유 경로를 등록하고, 검색 범위로 선택할 수 있게 한다.

!! PoC 범위 !! 실제 SMB 접속은 구현되어 있지 않다.
- ``unc_root`` : 화면과 결과에 표시되는 *원본 UNC 경로* (예: \\\\fs-actu01.example.invalid\\계리평가). 형식만 검증한다.
- ``local_dir``: 이 UNC 경로를 대신하는 ``data/shared_folder`` 아래의 *가상 폴더* 이름(하위 경로 불가).
실제 연동 시에는 SMB 클라이언트 구현체가 ``unc_root`` 를 직접 읽고, 접속 계정/자격증명은 별도 보안 설계가 필요하다.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

_UNC_RE = re.compile(r'^\\\\[A-Za-z0-9][A-Za-z0-9._-]*(\\[^\\/:*?"<>|\x00-\x1f]+)+$')
MAX_NAME = 40


class ShareError(ValueError):
    """등록 입력 오류(사용자에게 그대로 보여줄 수 있는 메시지)."""


@dataclass(frozen=True)
class Share:
    name: str
    unc_root: str
    local_dir: str
    enabled: bool = True


def validate_unc(path: str) -> str:
    path = path.strip().rstrip("\\") if path else ""
    if not _UNC_RE.match(path):
        raise ShareError("UNC 경로 형식이 올바르지 않습니다. 예) \\\\서버이름\\공유이름\\하위폴더")
    return path


class ShareRegistry:
    def __init__(self, path: Path | str, base_dir: Path | str):
        self.path = Path(path)
        self.base_dir = Path(base_dir)

    def list(self) -> list[Share]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [Share(s["name"], s["unc_root"], s["local_dir"], bool(s.get("enabled", True)))
                    for s in data.get("shares", [])]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return []

    def enabled(self) -> list[Share]:
        return [s for s in self.list() if s.enabled]

    def _save(self, shares: list[Share]) -> None:
        notice = ""
        try:
            notice = json.loads(self.path.read_text(encoding="utf-8")).get("notice", "")
        except (OSError, json.JSONDecodeError):
            pass
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"notice": notice, "shares": [asdict(s) for s in shares]},
                                        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def unregistered_dirs(self) -> list[str]:
        """아직 등록되지 않은 가상 폴더 이름(등록 화면의 선택지)."""
        used = {s.local_dir for s in self.list()}
        if not self.base_dir.is_dir():
            return []
        return sorted(p.name for p in self.base_dir.iterdir()
                      if p.is_dir() and not p.name.startswith(".") and p.name not in used)

    def register(self, name: str, unc_root: str, local_dir: str) -> Share:
        name = (name or "").strip()
        if not name or len(name) > MAX_NAME:
            raise ShareError(f"표시 이름은 1~{MAX_NAME}자로 입력해 주세요.")
        unc = validate_unc(unc_root)
        local_dir = (local_dir or "").strip()
        if (not local_dir or local_dir in (".", "..") or any(ch in local_dir for ch in '/\\:') or
                local_dir.startswith(".")):
            raise ShareError("가상 폴더 이름이 올바르지 않습니다(하위 경로·상위 경로 지정 불가).")
        if not (self.base_dir / local_dir).is_dir():
            raise ShareError("선택한 가상 폴더를 찾을 수 없습니다.")
        shares = self.list()
        for s in shares:
            if s.name.casefold() == name.casefold():
                raise ShareError("이미 같은 표시 이름의 공유폴더가 있습니다.")
            if s.unc_root.casefold() == unc.casefold():
                raise ShareError("이미 등록된 UNC 경로입니다.")
            if s.local_dir == local_dir:
                raise ShareError("이미 다른 경로에 연결된 가상 폴더입니다.")
        new = Share(name, unc, local_dir, True)
        self._save(shares + [new])
        return new

    def unregister(self, name: str) -> bool:
        shares = self.list()
        kept = [s for s in shares if s.name != name]
        if len(kept) == len(shares):
            return False
        self._save(kept)
        return True

    def set_enabled(self, name: str, enabled: bool) -> bool:
        shares = self.list()
        changed = False
        out = []
        for s in shares:
            if s.name == name and s.enabled != enabled:
                s, changed = Share(s.name, s.unc_root, s.local_dir, enabled), True
            out.append(s)
        if changed:
            self._save(out)
        return changed
