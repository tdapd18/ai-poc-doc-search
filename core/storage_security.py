"""로컬 색인 저장소(본문 조각을 담을 수 있는 파일)의 보호 조치.

- ``harden_dir``      : 색인 폴더를 현재 계정 전용으로 제한한다 (POSIX 0700 / Windows 는 icacls 로 상속 제거 후 본인만 허용).
- ``find_residue``    : 색인 폴더에 남은 복사본·백업·임시·저널 파일(본문이 평문으로 남을 수 있음)을 찾는다.
- ``purge_residue``   : 위 잔존 파일을 0으로 덮어쓴 뒤 삭제한다. 살아 있는 색인(index.db)·설정은 건드리지 않는다.
- ``wipe_file``       : 파일 내용을 덮어쓴 뒤 삭제한다 (SSD/저널링 파일시스템에서는 완전한 소거를 보장하지 못한다).
- ``storage_warnings``: 클라우드 동기화 폴더(OneDrive 등)·권한 설정 실패 같은 위험을 사람이 읽을 문장으로 돌려준다.

어떤 함수도 예외를 밖으로 던지지 않고 결과를 돌려준다(보호 조치 실패가 앱 기동을 막지 않도록, 대신 경고로 알린다).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

LIVE_NAMES = {"index.db", "config.json", "shares.json", "audit.log"}
RESIDUE_SUFFIXES = (".bak", ".old", ".orig", ".tmp", ".temp", ".swp", ".copy", "~", ".db-journal", ".db-wal",
                    ".db-shm", ".db", ".sqlite", ".sqlite3", "-journal", "-wal", "-shm")
SYNC_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "icloud", "box sync", "sharepoint")


def harden_dir(path: Path | str) -> tuple[bool, str]:
    """폴더를 현재 계정 전용으로 제한한다. (성공 여부, 설명)"""
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(p, 0o700)
            return True, "폴더 권한을 소유자 전용(0700)으로 설정했습니다."
        user = os.environ.get("USERNAME", "")
        if not user:
            return False, "사용자 이름을 알 수 없어 폴더 권한을 제한하지 못했습니다."
        r = subprocess.run(["icacls", str(p), "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)F"],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            return True, "폴더 접근을 현재 Windows 계정으로 제한했습니다."
        return False, "폴더 권한 제한(icacls)에 실패했습니다. 폴더 속성에서 직접 확인하세요."
    except Exception:
        return False, "폴더 권한을 제한하지 못했습니다."


def wipe_file(path: Path | str) -> bool:
    """내용을 0으로 덮어쓰고 삭제한다. 삭제에 성공하면 True."""
    p = Path(path)
    try:
        if p.is_file():
            size = p.stat().st_size
            with open(p, "r+b") as f:
                remaining = size
                while remaining > 0:
                    n = min(remaining, 1 << 20)
                    f.write(b"\0" * n)
                    remaining -= n
                f.flush()
                os.fsync(f.fileno())
        p.unlink(missing_ok=True)
        return not p.exists()
    except Exception:
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
        return not p.exists()


def find_residue(home: Path | str) -> list[Path]:
    """색인 폴더 안의 잔존 가능 파일. 살아 있는 파일(index.db 등)은 제외한다."""
    h = Path(home)
    out: list[Path] = []
    try:
        for p in h.iterdir():
            if not p.is_file() or p.name in LIVE_NAMES:
                continue
            low = p.name.lower()
            if low.endswith(RESIDUE_SUFFIXES) or low.startswith("index.db") or low.startswith("index."):
                out.append(p)
    except OSError:
        pass
    return sorted(out)


def purge_residue(home: Path | str, *, keep_journal: bool = False) -> int:
    """잔존 파일을 덮어쓰고 삭제한다. 삭제한 개수를 돌려준다. ``keep_journal`` 은 사용 중인 저널을 지우지 않기 위한 옵션."""
    n = 0
    for p in find_residue(home):
        if keep_journal and p.name.lower().endswith(("-journal", ".db-journal", "-wal", "-shm")):
            continue
        if wipe_file(p):
            n += 1
    return n


def storage_warnings(home: Path | str) -> list[str]:
    h = Path(home)
    msgs: list[str] = []
    low = str(h.resolve() if h.exists() else h).lower()
    if any(m in low for m in SYNC_MARKERS):
        msgs.append("색인 폴더가 클라우드 동기화 폴더(OneDrive 등) 안에 있습니다. 색인(본문 포함)이 외부로 복제될 수 있으니 "
                    "동기화되지 않는 로컬 폴더(APP_HOME)로 옮기세요.")
    if os.name == "posix":
        try:
            if h.exists() and (h.stat().st_mode & 0o077):
                msgs.append("색인 폴더에 다른 사용자의 접근 권한이 열려 있습니다.")
        except OSError:
            pass
    left = find_residue(h)
    if left:
        msgs.append(f"색인 폴더에 백업·임시 파일로 보이는 파일이 {len(left)}개 남아 있습니다 (설정 화면에서 안전 삭제할 수 있습니다).")
    return msgs
