"""파일시스템 추상화 — 실제 Windows UNC 읽기와 합성(테스트) 파일시스템을 같은 인터페이스로 다룬다.

경로는 모든 계층에서 **UNC 문자열(`\\\\서버\\공유\\폴더\\파일.ext`, 구분자 `\\`)** 이다.

구현체
- ``LocalFS``  : 운영 체제의 파일 API 를 그대로 사용한다. Windows 에서는 UNC 경로를 직접 읽으며(로그인한 계정의 권한이
                 운영 체제에 의해 적용된다), 긴 경로(260자 초과)는 ``\\\\?\\UNC\\`` 확장 경로로 변환한다.
                 !! 이 클래스의 Windows 전용 경로는 Linux 개발 환경에서 실행·검증할 수 없다(문자열 변환만 테스트). !!
- ``MappedFS`` : UNC 루트를 로컬 폴더에 매핑한다(데모 가상 공유, 합성 Windows 공유 테스트). Windows 의 대소문자 비구분
                 경로 해석, 접근 거부, 공유 오프라인, 파일 잠금, 순회 중 삭제, 읽는 중 변경을 **주입**해 모사할 수 있다.

오류는 세 종류로 분류한다(동기화 정책이 다르다).
  FsAccessDenied : 권한 없음            → 색인에서 제거(fail-closed)
  FsNotFound     : 없음/삭제            → 색인에서 제거
  FsUnavailable  : 네트워크/잠금/시간초과 → 기존 색인은 유지하되 조회에서 숨김(재시도)
"""
from __future__ import annotations

import errno
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class FsError(Exception):
    """파일시스템 오류. 메시지에는 경로·내용을 담지 않는다."""


class FsAccessDenied(FsError):
    pass


class FsNotFound(FsError):
    pass


class FsUnavailable(FsError):
    pass


@dataclass(frozen=True)
class FsEntry:
    name: str
    path: str  # UNC 경로
    is_dir: bool
    size: int = 0
    mtime_ns: int = 0
    created_ns: int = 0
    is_link: bool = False  # 심볼릭 링크 / 접합(junction) / 재분석 지점


@dataclass(frozen=True)
class FsStat:
    size: int
    mtime_ns: int
    created_ns: int = 0

    @property
    def fingerprint(self) -> str:
        return f"{self.size}:{self.mtime_ns}"


# ------------------------------------------------------------------ UNC 문자열 도우미
def normalize_unc(path: str) -> str:
    """끝 구분자 제거, 중복 구분자 정리(앞의 `\\\\` 는 유지)."""
    path = path.strip()
    lead = "\\\\" if path.startswith("\\\\") else ""
    body = path[len(lead):]
    while "\\\\" in body:
        body = body.replace("\\\\", "\\")
    return lead + body.rstrip("\\")


def unc_key(path: str) -> str:
    """Windows 는 경로 대소문자를 구분하지 않으므로 식별용 키는 casefold 한다."""
    return normalize_unc(path).casefold()


def unc_join(base: str, *names: str) -> str:
    out = normalize_unc(base)
    for n in names:
        out = out + "\\" + n.strip("\\")
    return out


def unc_relative(root: str, path: str) -> str:
    """root 아래의 상대 경로(구분자 `\\`). root 밖이면 ValueError."""
    r, p = normalize_unc(root), normalize_unc(path)
    if p.casefold() == r.casefold():
        return ""
    if not p.casefold().startswith(r.casefold() + "\\"):
        raise ValueError("경로가 루트 밖입니다")
    return p[len(r) + 1:]


def unc_parent(path: str) -> str:
    p = normalize_unc(path)
    return p.rsplit("\\", 1)[0] if "\\" in p[2:] else p


def to_extended_path(path: str) -> str:
    """Windows 긴 경로 접두사 변환. `\\\\srv\\sh\\x` → `\\\\?\\UNC\\srv\\sh\\x`, `C:\\x` → `\\\\?\\C:\\x`."""
    if path.startswith("\\\\?\\") or path.startswith("\\\\.\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    if len(path) > 2 and path[1] == ":":
        return "\\\\?\\" + path
    return path


# ------------------------------------------------------------------ 인터페이스
class FileSystem(ABC):
    @abstractmethod
    def scandir(self, path: str) -> list[FsEntry]:
        """디렉터리 목록. 권한/없음/불가 시 FsError 하위 예외."""

    @abstractmethod
    def stat(self, path: str) -> FsStat: ...

    @abstractmethod
    def read_bytes(self, path: str, max_bytes: int) -> bytes:
        """파일 전체를 읽는다(최대 max_bytes+1 바이트까지만 읽어 한도 초과를 호출자가 판단)."""

    @abstractmethod
    def check_open(self, path: str) -> None:
        """읽기용으로 열 수 있는지 **실제로 열어서** 확인한다(내용은 읽지 않는다). 불가 시 FsError."""

    def exists_dir(self, path: str) -> bool:
        try:
            self.scandir(path)
            return True
        except FsError:
            return False


def classify_oserror(exc: OSError) -> FsError:
    """OSError → FsError 분류 (Windows winerror 포함). 메시지에 경로를 넣지 않는다."""
    winerr = getattr(exc, "winerror", None)
    if isinstance(exc, PermissionError) and winerr not in (32, 33):
        return FsAccessDenied("접근 권한이 없습니다")
    if winerr in (5, 1314) or exc.errno in (errno.EACCES, errno.EPERM):
        return FsAccessDenied("접근 권한이 없습니다")
    if winerr in (2, 3, 123, 206) or exc.errno in (errno.ENOENT, errno.ENOTDIR):
        return FsNotFound("경로를 찾을 수 없습니다")
    if winerr in (32, 33):
        return FsUnavailable("다른 프로그램이 파일을 사용 중입니다")
    if winerr in (53, 55, 64, 67, 121, 1219, 1231, 1396) or exc.errno in (errno.ETIMEDOUT, errno.EHOSTUNREACH,
                                                                           errno.ENETUNREACH, errno.ECONNRESET):
        return FsUnavailable("네트워크 경로에 연결할 수 없습니다")
    return FsUnavailable("파일시스템 오류")


# ------------------------------------------------------------------ 운영 체제 직접 사용
class LocalFS(FileSystem):
    """OS 파일 API 직접 사용. Windows 에서는 UNC 경로를 확장 경로로 변환해 읽는다."""

    def __init__(self, extended_paths: bool | None = None):
        self.extended = (sys.platform == "win32") if extended_paths is None else extended_paths

    def _p(self, path: str) -> str:
        return to_extended_path(path) if self.extended else path

    def scandir(self, path: str) -> list[FsEntry]:
        out: list[FsEntry] = []
        try:
            with os.scandir(self._p(path)) as it:
                for e in it:
                    try:
                        link = e.is_symlink() or bool(getattr(e.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400)
                        is_dir = e.is_dir(follow_symlinks=False)
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue  # 목록에는 보이나 속성을 읽을 수 없는 항목은 건너뜀
                    out.append(FsEntry(e.name, unc_join(path, e.name), is_dir, 0 if is_dir else st.st_size,
                                       st.st_mtime_ns, getattr(st, "st_birthtime_ns", None) or st.st_ctime_ns, link))
        except OSError as exc:
            raise classify_oserror(exc) from None
        return out

    def stat(self, path: str) -> FsStat:
        try:
            st = os.stat(self._p(path))
        except OSError as exc:
            raise classify_oserror(exc) from None
        return FsStat(st.st_size, st.st_mtime_ns, getattr(st, "st_birthtime_ns", None) or st.st_ctime_ns)

    def read_bytes(self, path: str, max_bytes: int) -> bytes:
        try:
            with open(self._p(path), "rb") as f:
                return f.read(max_bytes + 1)
        except OSError as exc:
            raise classify_oserror(exc) from None

    def check_open(self, path: str) -> None:
        try:
            with open(self._p(path), "rb"):
                pass
        except OSError as exc:
            raise classify_oserror(exc) from None


# ------------------------------------------------------------------ 매핑 + 합성 장애 주입
class MappedFS(FileSystem):
    """UNC 루트 → 로컬 폴더 매핑. Windows 공유의 동작을 합성 데이터로 모사한다.

    주입 가능한 동작(테스트용)
      deny_list(prefix)   : 해당 폴더 목록 열람 거부(하위 포함)
      deny_read(prefix)   : 해당 파일/폴더 아래 파일 열기 거부 (목록에는 보임 — NTFS 에서 흔한 상태)
      offline(root)       : 공유 전체 불가(네트워크 단절)
      lock(path)          : 파일 잠금(공유 위반) → FsUnavailable
      vanish(path)        : 목록에는 있으나 읽을 때 사라짐 → FsNotFound
      on_read(callback)   : 읽기 직전 콜백(읽는 중 변경 모사)
    counters: ``reads``(본문을 읽은 경로), ``opens``(열기 확인한 경로), ``scans``(목록 조회한 경로)
    """

    def __init__(self, mapping: dict[str, Path | str]):
        self._map = {normalize_unc(k).casefold(): (normalize_unc(k), Path(v)) for k, v in mapping.items()}
        self._deny_list: set[str] = set()
        self._deny_read: set[str] = set()
        self._offline: set[str] = set()
        self._lock: set[str] = set()
        self._vanish: set[str] = set()
        self.on_read: Callable[[str], None] | None = None
        self.reads: list[str] = []
        self.opens: list[str] = []
        self.scans: list[str] = []

    # -- 주입 --------------------------------------------------------------
    def deny_list(self, prefix: str) -> None:
        self._deny_list.add(unc_key(prefix))

    def deny_read(self, prefix: str) -> None:
        self._deny_read.add(unc_key(prefix))

    def allow(self, prefix: str) -> None:
        for s in (self._deny_list, self._deny_read):
            s.discard(unc_key(prefix))

    def offline(self, root: str, on: bool = True) -> None:
        (self._offline.add if on else self._offline.discard)(unc_key(root))

    def lock(self, path: str, on: bool = True) -> None:
        (self._lock.add if on else self._lock.discard)(unc_key(path))

    def vanish(self, path: str, on: bool = True) -> None:
        (self._vanish.add if on else self._vanish.discard)(unc_key(path))

    # -- 내부 --------------------------------------------------------------
    @staticmethod
    def _under(key: str, prefixes: set[str]) -> bool:
        return any(key == p or key.startswith(p + "\\") for p in prefixes)

    def _root_for(self, path: str) -> tuple[str, Path, str]:
        key = unc_key(path)
        best = None
        for rk, (rname, rlocal) in self._map.items():
            if key == rk or key.startswith(rk + "\\"):
                if best is None or len(rk) > len(best[0]):
                    best = (rk, rname, rlocal)
        if best is None:
            raise FsNotFound("경로를 찾을 수 없습니다")
        rk, rname, rlocal = best
        rel = normalize_unc(path)[len(rname):].strip("\\")
        return rk, rlocal, rel

    def _check_online(self, key: str) -> None:
        if self._under(key, self._offline):
            raise FsUnavailable("네트워크 경로에 연결할 수 없습니다")

    def _resolve(self, local_root: Path, rel: str) -> Path:
        """Windows 처럼 대소문자를 구분하지 않고 경로를 찾는다. `..` 는 거부."""
        cur = local_root
        if not local_root.is_dir():
            raise FsNotFound("경로를 찾을 수 없습니다")
        for part in [p for p in rel.split("\\") if p]:
            if part in (".", ".."):
                raise FsNotFound("경로를 찾을 수 없습니다")
            cand = cur / part
            if cand.exists() or cand.is_symlink():
                cur = cand
                continue
            try:
                match = next((c for c in cur.iterdir() if c.name.casefold() == part.casefold()), None)
            except OSError:
                match = None
            if match is None:
                raise FsNotFound("경로를 찾을 수 없습니다")
            cur = match
        return cur

    # -- 인터페이스 ----------------------------------------------------------
    def scandir(self, path: str) -> list[FsEntry]:
        key = unc_key(path)
        self._check_online(key)
        self.scans.append(key)
        if self._under(key, self._deny_list):
            raise FsAccessDenied("접근 권한이 없습니다")
        _, local_root, rel = self._root_for(path)
        target = self._resolve(local_root, rel)
        if not target.is_dir():
            raise FsNotFound("경로를 찾을 수 없습니다")
        out = []
        try:
            children = sorted(target.iterdir(), key=lambda c: c.name.casefold())
        except OSError as exc:
            raise classify_oserror(exc) from None
        for c in children:
            try:
                st = c.lstat()
            except OSError:
                continue
            is_link = c.is_symlink()
            is_dir = c.is_dir() and not is_link
            out.append(FsEntry(c.name, unc_join(path, c.name), is_dir, 0 if is_dir else st.st_size, st.st_mtime_ns,
                               getattr(st, "st_birthtime_ns", None) or st.st_ctime_ns, is_link))
        return out

    def stat(self, path: str) -> FsStat:
        key = unc_key(path)
        self._check_online(key)
        _, local_root, rel = self._root_for(path)
        p = self._resolve(local_root, rel)
        try:
            st = p.stat()
        except OSError as exc:
            raise classify_oserror(exc) from None
        return FsStat(st.st_size, st.st_mtime_ns, getattr(st, "st_birthtime_ns", None) or st.st_ctime_ns)

    def _open_checks(self, path: str) -> Path:
        key = unc_key(path)
        self._check_online(key)
        if self._under(key, self._deny_read) or self._under(key, self._deny_list):
            raise FsAccessDenied("접근 권한이 없습니다")
        _, local_root, rel = self._root_for(path)
        p = self._resolve(local_root, rel)
        if key in self._vanish:
            raise FsNotFound("경로를 찾을 수 없습니다")
        if key in self._lock:
            raise FsUnavailable("다른 프로그램이 파일을 사용 중입니다")
        if not p.is_file():
            raise FsNotFound("경로를 찾을 수 없습니다")
        return p

    def read_bytes(self, path: str, max_bytes: int) -> bytes:
        p = self._open_checks(path)
        if self.on_read:
            self.on_read(normalize_unc(path))
        self.reads.append(unc_key(path))
        try:
            with open(p, "rb") as f:
                return f.read(max_bytes + 1)
        except OSError as exc:
            raise classify_oserror(exc) from None

    def check_open(self, path: str) -> None:
        p = self._open_checks(path)
        self.opens.append(unc_key(path))
        try:
            with open(p, "rb"):
                pass
        except OSError as exc:
            raise classify_oserror(exc) from None
