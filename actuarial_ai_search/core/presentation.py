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


def badge_html(label: str, kind: str) -> str:
    return f'<span class="badge badge-{html.escape(kind)}">{html.escape(label)}</span>'


SOURCE_KIND = {"shared_folder": "sf", "groupware": "gw", "business_system": "bs"}
