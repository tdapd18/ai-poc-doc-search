"""민감정보가 기록되지 않는 로깅.

원칙
- 문서 본문, 검색어 원문, 답변 원문은 로그에 남기지 않는다 (길이/개수/ID 만 기록).
- 비밀번호·API 키·토큰 패턴은 필터가 마지막으로 한 번 더 마스킹한다.
"""
from __future__ import annotations

import logging
import re

_SECRET_PATTERNS = [
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/\-]+=*"),  # 먼저 적용: "Authorization: Bearer xxx" 의 토큰까지 마스킹
    re.compile(r"(?i)(password|passwd|pwd|secret|api[_-]?key|token|authorization)\s*[=:]\s*\S+"),
    re.compile(r"sk-[A-Za-z0-9]{8,}"),
]


def redact(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def get_logger(name: str = "actuarial_search") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        handler.addFilter(RedactFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def log_event(logger: logging.Logger, event: str, **fields: object) -> None:
    """key=value 형태로 기록. 본문/검색어 같은 큰 텍스트 필드는 호출자가 넘기지 않는다."""
    parts = " ".join(f"{k}={v}" for k, v in fields.items())
    logger.info("%s %s", event, parts)
