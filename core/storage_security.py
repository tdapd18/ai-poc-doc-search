"""로컬 색인 저장소(본문 조각을 담을 수 있는 파일)의 보호 조치.

- ``check_storage``   : 색인 폴더가 안전한지 **검증**한다 (Windows 는 icacls /save 로 SDDL 을 읽어 넓은 범위 접근 여부 확인.
                        권한을 바꾸지 않는다 — SYSTEM·관리자 등 회사 정책 권한을 제거하면 중앙 관리와 충돌할 수 있다).
- ``find_residue``    : 색인 폴더에 남은 복사본·백업·임시·저널 파일(본문이 평문으로 남을 수 있음)을 찾는다.
- ``purge_residue``   : 위 잔존 파일을 0으로 덮어쓴 뒤 삭제한다. 살아 있는 색인(index.db)·설정은 건드리지 않는다.
- ``wipe_file``       : 파일 내용을 덮어쓴 뒤 삭제한다 (SSD/저널링 파일시스템에서는 완전한 소거를 보장하지 못한다).
- ``storage_warnings``: 클라우드 동기화 폴더(OneDrive 등)·권한 설정 실패 같은 위험을 사람이 읽을 문장으로 돌려준다.

어떤 함수도 예외를 밖으로 던지지 않고 결과를 돌려준다(보호 조치 실패가 앱 기동을 막지 않도록, 대신 경고로 알린다).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

LIVE_NAMES = {"index.db", "config.json", "shares.json", "audit.log"}
RESIDUE_SUFFIXES = (".bak", ".old", ".orig", ".tmp", ".temp", ".swp", ".copy", "~", ".db-journal", ".db-wal",
                    ".db-shm", ".db", ".sqlite", ".sqlite3", "-journal", "-wal", "-shm")
SYNC_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "icloud", "box sync", "sharepoint")


# 일반 사용자 전원·인증 사용자 전원·게스트 등 "넓은 범위" 보안 주체 (SDDL 약어 또는 SID)
BROAD_SIDS = {"WD", "BU", "AU", "IU", "NU", "AN", "DU", "DG", "DC", "BG", "S-1-1-0", "S-1-5-32-545", "S-1-5-32-546",
              "S-1-5-11", "S-1-5-4", "S-1-5-2", "S-1-5-7", "S-1-5-32-554"}
_DOMAIN_BROAD = re.compile(r"^S-1-5-21-[\d-]+-(513|514|515)$")  # Domain Users / Guests / Computers


@dataclass(frozen=True)
class StorageStatus:
    """로컬 색인 저장 위치의 보호 검증 결과. 앱은 권한을 *바꾸지 않고* 확인만 한다(회사 중앙 보안정책과 충돌 방지).

    - allow_index      : 새 색인 생성(공유폴더 읽기) 허용
    - allow_body       : 본문(조각) 검색·표시 허용
    - allow_full_text  : 본문 색인 모드로 전환·유지 허용
    메시지는 사용자 안내용이며 경로·계정 같은 내부 보안정보를 담지 않는다.
    """
    verified: bool = True            # 보호 상태를 실제로 확인했는가
    private: bool = True             # 계정 전용(넓은 범위 접근 없음)으로 확인되었는가
    cloud_sync: bool = False
    index_ok: bool = True            # 색인 파일을 열고 복구할 수 있는가
    reasons: tuple[str, ...] = ()
    messages: tuple[str, ...] = ()

    @property
    def allow_index(self) -> bool:
        return self.private and self.verified and self.index_ok

    @property
    def allow_body(self) -> bool:
        return self.allow_index and not self.cloud_sync

    @property
    def allow_full_text(self) -> bool:
        return self.allow_body

    def with_(self, **kw) -> "StorageStatus":
        return replace(self, **kw)


def is_cloud_sync_path(path: Path | str, env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    try:
        low = str(Path(path).resolve()).lower().replace("\\", "/")
    except OSError:
        low = str(path).lower().replace("\\", "/")
    if any(m in low for m in SYNC_MARKERS):
        return True
    for var in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        root = env.get(var) or env.get(var.upper())
        if root:
            r = str(root).lower().replace("\\", "/").rstrip("/")
            if r and (low == r or low.startswith(r + "/")):
                return True
    return False


def parse_sddl_broad_access(sddl: str) -> list[str]:
    """SDDL 문자열에서 넓은 범위 주체에 부여된 허용(allow) ACE 를 찾아 trustee 목록으로 돌려준다."""
    dacl = sddl.split("D:", 1)[1] if "D:" in sddl else ""
    dacl = dacl.split("S:", 1)[0]
    found: list[str] = []
    for ace in re.findall(r"\(([^()]*)\)", dacl):
        f = ace.split(";")
        if len(f) < 6 or f[0] not in ("A", "OA"):
            continue
        trustee = f[5].strip().upper()
        if trustee in BROAD_SIDS or _DOMAIN_BROAD.match(trustee):
            found.append(trustee)
    return found


def read_sddl_icacls(path: Path) -> str | None:
    """Windows: ``icacls <경로> /save`` 로 DACL 을 SDDL(SID 기반, 언어 독립)로 읽는다. 읽기 전용 — 권한을 바꾸지 않는다."""
    try:
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "acl.txt"
            r = subprocess.run(["icacls", str(path), "/save", str(out)], capture_output=True, text=True, timeout=20)
            if r.returncode != 0 or not out.is_file():
                return None
            raw = out.read_bytes()
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "ignore")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return next((ln for ln in reversed(lines) if ln.startswith(("D:", "O:"))), None)
    except Exception:
        return None


def check_storage(home: Path | str, *, platform: str | None = None, acl_reader=None, env: dict | None = None) -> StorageStatus:
    """로컬 색인 폴더가 본문 조각을 저장해도 되는 위치인지 **검증**한다 (변경·우회하지 않는다).

    통과 조건: ① 동기화 폴더(OneDrive 등)가 아님(아니면 본문 차단) ② 폴더·색인 파일에 넓은 범위 접근이 없음
    ③ 위 사실을 실제로 읽어 확인할 수 있음. 확인하지 못하면(명령 실패 포함) '안전'으로 간주하지 않고 차단한다.
    """
    platform = platform or sys.platform
    home = Path(home)
    reasons: list[str] = []
    msgs: list[str] = []
    verified, private = True, True
    cloud = is_cloud_sync_path(home, env)
    if cloud:
        reasons.append("cloud_sync")
        msgs.append("색인 저장 위치가 클라우드 동기화 폴더(OneDrive 등)입니다. 본문 색인과 본문 표시를 차단했습니다. "
                    "회사가 승인한 동기화되지 않는 로컬 경로(APP_HOME)를 지정하세요.")
    try:
        home.mkdir(parents=True, exist_ok=True)
    except OSError:
        return StorageStatus(False, False, cloud, True, tuple(reasons + ["not_writable"]),
                             tuple(msgs + ["색인 저장 폴더를 만들거나 열 수 없어 색인 생성을 차단했습니다."]))
    targets = [home] + ([home / "index.db"] if (home / "index.db").exists() else [])
    if platform == "win32":
        reader = acl_reader or read_sddl_icacls
        for t in targets:
            sddl = None
            try:
                sddl = reader(t)
            except Exception:
                sddl = None
            if not sddl:
                verified = False
            elif parse_sddl_broad_access(sddl):
                private = False
        if not verified:
            reasons.append("acl_unverifiable")
            msgs.append("색인 저장 폴더의 접근 권한을 확인하지 못해 색인 생성과 본문 표시를 차단했습니다. "
                        "정보보안 담당자에게 이 PC의 폴더 권한 조회(icacls) 허용 여부를 문의하세요.")
        if not private:
            reasons.append("acl_broad_access")
            msgs.append("색인 저장 폴더에 일반 사용자 전체(Everyone/Users 등)가 접근할 수 있는 권한이 있어 색인 생성과 본문 표시를 차단했습니다. "
                        "사용자 프로필 안의 계정 전용 경로를 사용하세요. (회사 정책을 앱이 임의로 변경하지 않습니다)")
    else:
        for t in targets:
            try:
                st = t.stat()
                if st.st_uid != os.getuid():
                    private = False
                elif st.st_mode & 0o077:
                    if t == home:
                        os.chmod(t, 0o700)  # 앱이 만든 개인 폴더에 한해 소유자 전용으로 맞춘다
                    else:
                        os.chmod(t, 0o600)
                    st = t.stat()
                    if st.st_mode & 0o077:
                        private = False
            except OSError:
                verified = False
        if not verified:
            reasons.append("acl_unverifiable")
            msgs.append("색인 저장 폴더의 권한을 확인하지 못해 색인 생성과 본문 표시를 차단했습니다.")
        if not private:
            reasons.append("dir_not_private")
            msgs.append("색인 저장 폴더가 현재 계정 전용이 아니어서 색인 생성과 본문 표시를 차단했습니다.")
    return StorageStatus(verified, private, cloud, True, tuple(reasons), tuple(msgs))


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


def storage_warnings(home: Path | str, status: StorageStatus | None = None) -> list[str]:
    msgs: list[str] = list(status.messages) if status else list(check_storage(home).messages)
    left = find_residue(Path(home))
    if left:
        msgs.append(f"색인 폴더에 백업·임시 파일로 보이는 파일이 {len(left)}개 남아 있습니다 (설정 화면에서 안전 삭제할 수 있습니다).")
    return msgs
