"""화면 표시용 안전한 HTML 조각 생성. 문서 본문은 신뢰할 수 없으므로 항상 이스케이프한 뒤 강조를 입힌다."""
from __future__ import annotations

import html
import re


def safe_highlight_html(text: str, terms: tuple[str, ...] | list[str] = ()) -> str:
    """텍스트를 HTML 이스케이프하고 질의어를 <mark> 로 강조한다. 줄바꿈은 <br> 로 유지."""
    escaped = html.escape(text)
    usable = sorted({html.escape(t) for t in terms if t and len(t) >= 2}, key=len, reverse=True)
    if usable:
        pattern = re.compile("|".join(re.escape(t) for t in usable), re.IGNORECASE)
        escaped = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", escaped)
    return escaped.replace("\n", "<br>")


def path_html(path: str) -> str:
    """경로를 마크다운 안의 HTML 로 안전하게 출력한다. 역슬래시(UNC)는 마크다운이 이스케이프로 해석해
    `\\\\서버`가 `\\서버`로 줄어드는 것을 막기 위해 문자 참조(&#92;)로 바꾼다."""
    return html.escape(path).replace("\\", "&#92;")


def badge_html(label: str, kind: str) -> str:
    return f'<span class="badge badge-{html.escape(kind)}">{html.escape(label)}</span>'


SOURCE_KIND = {"shared_folder": "sf", "groupware": "gw", "business_system": "bs"}


# 문서 유형별 배지 색상 클래스 (app.py CSS 와 연결)
TYPE_KIND = {"pdf": "pdf", "xlsx": "xls", "pptx": "ppt", "md": "txt", "txt": "txt", "post": "gw", "record": "bs"}


def make_snippet(text: str, terms: tuple[str, ...] | list[str], before: int = 45, after: int = 140) -> str:
    """첫 번째 일치 위치 주변만 잘라 보여준다 (DocFetcher 식 일치 문맥 발췌). 일치가 없으면 앞부분."""
    flat = re.sub(r"\s*\n\s*", " ⏎ ", text.strip())
    usable = [t for t in terms if t and len(t) >= 2]
    first = None
    if usable:
        m = re.search("|".join(re.escape(t) for t in sorted(usable, key=len, reverse=True)), flat, re.IGNORECASE)
        first = m.start() if m else None
    if first is None:
        return flat[: before + after] + ("…" if len(flat) > before + after else "")
    start = max(0, first - before)
    end = min(len(flat), first + after)
    return ("…" if start > 0 else "") + flat[start:end] + ("…" if end < len(flat) else "")


def folder_of(path: str) -> str:
    """UNC 경로(또는 URL)에서 파일명을 뺀 상위 경로."""
    for sep in ("\\", "/"):
        if sep in path:
            return path.rsplit(sep, 1)[0]
    return path
