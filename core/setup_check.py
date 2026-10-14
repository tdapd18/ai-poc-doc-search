"""공유폴더 연결 테스트와 색인 전 사전 점검(드라이런).

**파일 내용을 읽지 않는다.** 폴더 목록(이름·크기·수정시각)과 '파일을 열 수 있는지' 확인(열고 바로 닫음)만 수행한다.
따라서 본문 검색 승인 전에도 안전하게 실행할 수 있다. 결과에는 파일 이름 대신 건수·형식별 통계만 담는다.
"""
from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass, field

from core.app_config import AppConfig
from core.fs import FileSystem, FsAccessDenied, FsNotFound, FsUnavailable, unc_join
from core.shares import Share, ShareError, validate_unc

SUPPORTED = {"md", "txt", "pdf", "docx", "xlsx", "xlsm", "pptx", "csv"}
LEGACY = {"doc", "xls", "ppt", "hwp", "hwpx"}


@dataclass
class ConnectionTestResult:
    ok: bool = False
    stage: str = ""  # path | connect | list | scan | permission | done
    code: str = ""  # ok | invalid_path | denied | not_found | unavailable
    message: str = ""
    latency_ms: int = 0
    top_folders: int = 0
    top_files: int = 0
    scanned_entries: int = 0
    truncated: bool = False  # 시간/개수 한도로 일부만 점검
    by_ext: dict[str, int] = field(default_factory=dict)  # 색인 대상 형식별 파일 수
    unsupported: int = 0
    legacy: int = 0
    total_bytes: int = 0
    oversize: int = 0
    denied_dirs: int = 0
    sampled: int = 0
    readable: int = 0
    denied: int = 0
    transient: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def indexable(self) -> int:
        return sum(self.by_ext.values()) + self.legacy


def check_share(share: Share, fs: FileSystem, cfg: AppConfig, *, sample_files: int = 25, scan_limit: int = 5000,
               time_budget_s: float = 10.0, clock=time.monotonic) -> ConnectionTestResult:
    r = ConnectionTestResult()
    # 1) 경로 형식
    r.stage = "path"
    try:
        validate_unc(share.unc_root)
    except ShareError as exc:
        r.code, r.message = "invalid_path", str(exc)
        return r
    # 2) 연결 + 최상위 목록
    r.stage = "connect"
    t0 = clock()
    try:
        top = fs.scandir(share.unc_root)
    except FsAccessDenied:
        r.code, r.message = "denied", "이 Windows 계정으로는 공유에 접근할 수 없습니다. 권한(공유/NTFS)을 확인하거나 담당자에게 접근 권한을 요청하세요."
        return r
    except FsNotFound:
        r.code, r.message = "not_found", "경로를 찾을 수 없습니다. 서버 이름과 공유 이름이 정확한지 확인하세요."
        return r
    except FsUnavailable:
        r.code, r.message = "unavailable", "공유에 연결할 수 없습니다. 사내망/VPN 연결, 서버 상태, 방화벽(SMB 445)을 확인하세요."
        return r
    r.latency_ms = int((clock() - t0) * 1000)
    r.stage = "list"
    r.top_folders = sum(1 for e in top if e.is_dir)
    r.top_files = len(top) - r.top_folders
    # 3) 제한된 범위의 사전 점검(드라이런): 형식별 통계
    r.stage = "scan"
    deadline = clock() + time_budget_s
    excludes = [p.casefold() for p in (*cfg.exclude_patterns, *share.exclude)]
    stack = [(share.unc_root, 0, top)]
    samples: list[str] = []
    max_bytes = cfg.max_file_mb * 1024 * 1024
    while stack:
        path, depth, entries = stack.pop()
        if entries is None:
            try:
                entries = fs.scandir(path)
            except FsAccessDenied:
                r.denied_dirs += 1
                continue
            except (FsNotFound, FsUnavailable):
                r.transient += 1
                continue
        for e in sorted(entries, key=lambda x: x.name.casefold()):
            if r.scanned_entries >= scan_limit or clock() > deadline:  # 폴더·파일 구분 없이 항목 수/시간 한도 적용
                r.truncated = True
                stack.clear()
                break
            if e.name.startswith(".") or any(fnmatch.fnmatch(e.name.casefold(), p) for p in excludes) or e.is_link:
                continue
            r.scanned_entries += 1
            if e.is_dir:
                if depth < cfg.max_depth:
                    stack.append((e.path, depth + 1, None))
                continue
            ext = e.name.rsplit(".", 1)[-1].lower() if "." in e.name else ""
            if ext in SUPPORTED:
                key = "xlsx" if ext == "xlsm" else ext
                r.by_ext[key] = r.by_ext.get(key, 0) + 1
                r.total_bytes += e.size
                if e.size > max_bytes:
                    r.oversize += 1
                if len(samples) < sample_files and (r.scanned_entries % 3 == 0 or len(samples) < 5):
                    samples.append(e.path)
            elif ext in LEGACY:
                r.legacy += 1
                r.total_bytes += e.size
            else:
                r.unsupported += 1
    if r.truncated:
        r.warnings.append("공유가 커서 일부만 점검했습니다. 통계는 추정치입니다.")
    # 4) 권한 표본: 파일을 열 수 있는지만 확인(내용 미열람)
    r.stage = "permission"
    for p in samples:
        r.sampled += 1
        try:
            fs.check_open(p)
            r.readable += 1
        except FsAccessDenied:
            r.denied += 1
        except (FsNotFound, FsUnavailable):
            r.transient += 1
    if r.denied:
        r.warnings.append(f"표본 {r.sampled}건 중 {r.denied}건은 이 계정으로 읽을 수 없습니다. 읽을 수 없는 파일은 색인되지 않습니다.")
    if r.denied_dirs:
        r.warnings.append(f"접근할 수 없는 하위 폴더 {r.denied_dirs}개는 색인되지 않습니다.")
    if r.oversize:
        r.warnings.append(f"크기 한도({cfg.max_file_mb}MB)를 넘는 파일 {r.oversize}개는 파일명 검색만 가능합니다.")
    r.stage, r.ok, r.code = "done", True, "ok"
    r.message = "연결 성공"
    return r
