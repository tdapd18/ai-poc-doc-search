"""앱 설정 · 보안 모드 승인 기록 · 감사 로그.

저장 위치(홈 폴더): Windows `%LOCALAPPDATA%\\ActuarialDocSearch`, 그 외 `~/.actuarial_doc_search`, 환경변수 `APP_HOME` 로 변경.
- config.json : 모드와 한도 (본문 저장 없음)
- audit.log   : 설정·공유 등록·색인 실행의 **건수/상태만** 기록(파일명·경로·내용·검색어 없음)

색인 수준
- metadata_only (기본) : 파일 이름·경로·형식·수정일·크기만 색인한다. 파일 내용은 읽지 않는다.
- full_text           : 본문을 추출해 로컬 색인에 저장한다. **회사 보안 승인 확인 기록이 있어야 켤 수 있다.**
  이 확인은 절차적 통제(사용자가 설정 파일을 직접 고칠 수 있음)이며, 승인 자체를 증명하지 않는다.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

INDEX_MODES = ("metadata_only", "full_text")
APP_MODES = ("demo", "real")
APPROVAL_STATEMENT = ("본문 검색(파일 내용 추출 및 이 PC의 로컬 색인 저장)에 대해 회사 정보보안 승인을 받았으며, "
                      "승인 범위 내에서만 사용합니다.")
DEFAULT_EXCLUDES = ["~$*", "*.tmp", "Thumbs.db", "desktop.ini", ".DS_Store", "$RECYCLE.BIN", "System Volume Information",
                    ".git", ".svn"]


class ConfigError(ValueError):
    """설정 오류(사용자에게 보여줄 수 있는 메시지)."""


def default_home() -> Path:
    env = os.environ.get("APP_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "ActuarialDocSearch"
    return Path.home() / ".actuarial_doc_search"


@dataclass
class Approval:
    approved: bool = False
    approver: str = ""  # 승인 담당자/문서 번호 등 사용자가 입력한 참조
    approved_at: str = ""
    statement: str = ""


@dataclass
class AppConfig:
    mode: str = "demo"  # demo | real
    index_mode: str = "metadata_only"
    approval: Approval = field(default_factory=Approval)
    max_file_mb: int = 20
    max_files_per_share: int = 200_000
    max_depth: int = 40
    exclude_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    verify_open_in_metadata_mode: bool = True  # 메타 전용에서도 권한 확인을 위해 파일을 열어 본다(내용은 읽지 않음)

    @property
    def full_text(self) -> bool:
        return self.index_mode == "full_text" and self.approval.approved


class ConfigStore:
    def __init__(self, home: Path | str | None = None):
        self.home = Path(home) if home else default_home()
        self.path = self.home / "config.json"
        self.audit_path = self.home / "audit.log"

    def load(self) -> AppConfig:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AppConfig()
        cfg = AppConfig()
        for k, v in data.items():
            if k == "approval" and isinstance(v, dict):
                cfg.approval = Approval(**{f: v.get(f, getattr(cfg.approval, f)) for f in asdict(cfg.approval)})
            elif hasattr(cfg, k) and k != "approval":
                setattr(cfg, k, v)
        if cfg.mode not in APP_MODES:
            cfg.mode = "demo"
        if cfg.index_mode not in INDEX_MODES:
            cfg.index_mode = "metadata_only"
        if cfg.index_mode == "full_text" and not cfg.approval.approved:
            cfg.index_mode = "metadata_only"  # 승인 기록 없는 본문 모드는 무효 → 안전한 기본값
        return cfg

    def save(self, cfg: AppConfig) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.home, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(asdict(cfg), f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)  # 원자적 교체
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        if os.name == "posix":
            os.chmod(self.path, 0o600)

    def set_index_mode(self, cfg: AppConfig, mode: str, *, approver: str = "", acknowledged: bool = False) -> bool:
        """색인 수준을 바꾼다. 바뀌었으면 True (호출자는 색인을 초기화해야 한다)."""
        if mode not in INDEX_MODES:
            raise ConfigError("알 수 없는 색인 수준입니다.")
        if mode == "full_text":
            if not acknowledged or not approver.strip():
                raise ConfigError("본문 검색은 보안 승인 확인과 승인 참조(담당자/문서 번호) 입력이 필요합니다.")
            cfg.approval = Approval(True, approver.strip(), datetime.now().isoformat(timespec="seconds"),
                                    APPROVAL_STATEMENT)
        else:
            cfg.approval = Approval()  # 메타 전용으로 돌아가면 승인 기록도 해제
        if cfg.index_mode == mode:
            self.save(cfg)
            return False
        cfg.index_mode = mode
        self.save(cfg)
        self.audit("index_mode_changed", mode=mode)
        return True

    def audit(self, event: str, **fields: object) -> None:
        """건수/상태만 기록한다. 문자열 값은 80자로 자르고 경로 구분자가 들어 있으면 기록하지 않는다."""
        safe = {}
        for k, v in fields.items():
            if isinstance(v, str) and ("\\" in v or "/" in v):
                continue
            safe[k] = v[:80] if isinstance(v, str) else v
        self.home.mkdir(parents=True, exist_ok=True)
        line = datetime.now().isoformat(timespec="seconds") + " " + event + " " + json.dumps(safe, ensure_ascii=False)
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def demo_config() -> AppConfig:
    """데모(가상 데이터) 모드용: 본문 색인. 가상 자료이므로 승인 절차를 적용하지 않는다."""
    return AppConfig(mode="demo", index_mode="full_text", approval=Approval(True, "demo", "", "가상 더미데이터"))
