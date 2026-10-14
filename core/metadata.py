"""`.meta.json` 없이 실제 업무문서를 색인하기 위한 자동 메타데이터 도출.

도출 규칙 (우선순위 순; 파일 안/옆에 명시된 메타데이터가 있으면 항상 그것이 우선한다)
- 문서 ID   : `F-` + 정규화 UNC 경로(casefold)의 SHA-1 앞 14자리  → 같은 경로는 항상 같은 ID, 이름 변경/이동은 삭제+신규
- 제목      : 문서 속성(docx/xlsx/pptx 제목)이 의미 있으면 그것, 아니면 파일명(확장자 제외, `_` → 공백)
- 수정일    : 파일 수정 시각(로컬 날짜)   / 작성일: 파일 생성 시각 (수정일보다 늦으면 수정일로 보정)
- 버전      : 파일명의 `v1.2`, `_v3`, `ver2`, `rev3`, `(최종)`, `final` 패턴, 없으면 `-`
- 부서      : 공유 루트 바로 아래 폴더명(없으면 공유 이름)
- 분류      : 경로+제목의 키워드 규칙(IFRS17/RAFM/결산), 없으면 기타 (규칙은 data/metadata/category_rules.json 에서 수정)
접근 권한은 도출하지 않는다 — 실제 모드에서는 운영 체제(파일 열기)가 판정한다.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from core.fs import unc_key

DEFAULT_CATEGORY_RULES = {
    "IFRS17": ["ifrs17", "ifrs 17", "ifrs-17", "csm", "goc", "보험계약마진", "보험계약집단", "이행현금흐름"],
    "RAFM": ["rafm", "모델 실행", "모델실행", "모델링", "모델별"],
    "결산": ["결산", "마감", "closing", "검증결과"],
}
_VERSION_PATTERNS = [
    re.compile(r"(?:^|[\s_\-\(\[])v(?:er(?:sion)?)?[\s._]?(\d+(?:\.\d+){0,2})(?=$|[\s_\-\)\].])", re.I),
    re.compile(r"(?:^|[\s_\-\(\[])rev[\s._]?(\d+)(?=$|[\s_\-\)\].])", re.I),
]
_FINAL_RE = re.compile(r"(최종|final)", re.I)


def load_category_rules(path: Path | str | None) -> dict[str, list[str]]:
    if path:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return {k: [t.lower() for t in v] for k, v in data.items() if isinstance(v, list)}
        except (OSError, json.JSONDecodeError):
            pass
    return DEFAULT_CATEGORY_RULES


def auto_doc_id(unc_path: str) -> str:
    return "F-" + hashlib.sha1(unc_key(unc_path).encode("utf-8")).hexdigest()[:14]


def title_from_filename(file_name: str) -> str:
    stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    return re.sub(r"\s+", " ", stem.replace("_", " ")).strip() or file_name


def guess_version(file_name: str) -> str:
    stem = file_name.rsplit(".", 1)[0]
    for pat in _VERSION_PATTERNS:
        m = pat.search(stem)
        if m:
            return m.group(1)
    return "최종" if _FINAL_RE.search(stem) else "-"


def guess_category(text: str, rules: dict[str, list[str]] | None = None) -> str:
    t = text.lower()
    for cat, words in (rules or DEFAULT_CATEGORY_RULES).items():
        if any(w in t for w in words):
            return cat
    return "기타"


def _date(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9).date().isoformat() if ns > 0 else datetime.now().date().isoformat()


def derive_metadata(*, unc_path: str, rel_in_share: str, file_name: str, share_name: str, mtime_ns: int,
                    created_ns: int, doc_title: str = "", rules: dict[str, list[str]] | None = None) -> dict:
    """공통 문서 구조(to_common_document)에 넘길 메타데이터 dict 를 만든다."""
    folders = rel_in_share.split("\\")[:-1]
    modified = _date(mtime_ns)
    created = min(_date(created_ns), modified)
    title = doc_title.strip() if doc_title and len(doc_title.strip()) >= 2 else title_from_filename(file_name)
    return {
        "doc_id": auto_doc_id(unc_path),
        "title": title,
        "category": guess_category(f"{rel_in_share} {title}", rules),
        "version": guess_version(file_name),
        "created_at": created,
        "modified_at": modified,
        "department": folders[0] if folders else share_name,
        "location": unc_path,
        "location_detail": f"{share_name} / {rel_in_share.replace(chr(92), ' / ')}",
        "file_name": file_name,
        "share": share_name,
    }
