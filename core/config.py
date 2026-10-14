"""환경 설정. 외부 라이브러리 없이 환경변수/.env 만 읽는다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    llm_provider: str  # none | mock | internal
    top_k: int


def load_settings() -> Settings:
    _load_dotenv(PROJECT_ROOT / ".env")
    data_dir = Path(os.environ.get("DATA_DIR", PROJECT_ROOT / "data"))
    db_path = Path(os.environ.get("INDEX_DB_PATH", PROJECT_ROOT / "database" / "index.db"))
    provider = os.environ.get("LLM_PROVIDER", "none").strip().lower()
    if provider not in ("none", "mock", "internal"):
        provider = "none"
    try:
        top_k = max(1, min(5, int(os.environ.get("SEARCH_TOP_K", "5"))))
    except ValueError:
        top_k = 5
    return Settings(data_dir=data_dir, db_path=db_path, llm_provider=provider, top_k=top_k)
