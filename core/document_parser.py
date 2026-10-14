"""문서 파싱: 메타데이터(front matter) 해석, 공통 Document 변환, 문단 분할, 지시문 의심 문장 탐지."""
from __future__ import annotations

import re
from datetime import date

from core.models import CATEGORIES, Chunk, Document, InvalidDocumentError

REQUIRED_FIELDS = (
    "doc_id", "title", "category", "version", "created_at", "modified_at", "department", "location",
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{1,39}$")
MAX_BODY_CHARS = 200_000


# ---------------------------------------------------------------- front matter
def _parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [v.strip().strip('"').strip("'") for v in inner.split(",") if v.strip()] if inner else []
    return raw.strip('"').strip("'")


def parse_front_matter_ex(text: str) -> tuple[dict, str, int]:
    """``---`` 로 둘러싼 단순 key: value 메타데이터와 본문을 분리한다 (YAML 부분집합).

    세 번째 반환값은 본문 첫 줄이 파일의 몇 번째 줄 앞에 있는지(0-기준 줄 오프셋)로, 줄 번호 표기에 쓴다.
    """
    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise InvalidDocumentError("메타데이터 블록(---)이 없습니다")
    meta: dict = {}
    end = None
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            end = i
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise InvalidDocumentError(f"메타데이터 {i + 1}행 형식 오류")
        key, _, value = line.partition(":")
        meta[key.strip()] = _parse_value(value)
    if end is None:
        raise InvalidDocumentError("메타데이터 블록이 닫히지 않았습니다")
    rest = lines[end + 1:]
    leading_blank = next((k for k, ln in enumerate(rest) if ln.strip()), len(rest))
    return meta, "\n".join(rest).strip("\n"), end + 1 + leading_blank


def parse_front_matter(text: str) -> tuple[dict, str]:
    meta, body, _ = parse_front_matter_ex(text)
    return meta, body


# ---------------------------------------------------------------- 공통 문서 변환
def _check_date(name: str, value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        raise InvalidDocumentError(f"{name} 날짜 형식 오류 (YYYY-MM-DD 필요)") from None


def _as_tuple(value) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise InvalidDocumentError("접근권한 필드는 목록이어야 합니다")
    return tuple(str(v).strip() for v in value if str(v).strip())


def to_common_document(meta: dict, body: str, *, source_key: str, source_system: str,
                       segments: tuple = (), allow_empty_body: bool = False) -> Document:
    """저장소별 원본 구조에서 추출한 공통 필드(dict)를 ``Document`` 로 변환·검증한다."""
    for name in REQUIRED_FIELDS:
        value = meta.get(name)
        if value is None or not str(value).strip():
            raise InvalidDocumentError(f"필수 필드 누락: {name}")
    doc_id = str(meta["doc_id"]).strip()
    if not _ID_RE.match(doc_id):
        raise InvalidDocumentError("doc_id 형식 오류")
    if not allow_empty_body and (not body or not body.strip()):
        raise InvalidDocumentError("본문이 비어 있습니다")
    if len(body) > MAX_BODY_CHARS:
        raise InvalidDocumentError("본문 크기 제한 초과")
    category = str(meta["category"]).strip()
    if category not in CATEGORIES:
        category = "기타"
    return Document(
        doc_id=doc_id,
        title=str(meta["title"]).strip(),
        source_key=source_key,
        source_system=source_system,
        category=category,
        version=str(meta["version"]).strip(),
        created_at=_check_date("created_at", str(meta["created_at"]).strip()),
        modified_at=_check_date("modified_at", str(meta["modified_at"]).strip()),
        department=str(meta["department"]).strip(),
        location=str(meta["location"]).strip(),
        body=body.strip("\n"),
        allowed_users=_as_tuple(meta.get("allowed_users")),
        allowed_groups=_as_tuple(meta.get("allowed_groups")),
        location_detail=str(meta.get("location_detail", "")).strip(),
        attachments=_as_tuple(meta.get("attachments")),
        file_type=str(meta.get("file_type", "md")).strip() or "md",
        file_name=str(meta.get("file_name", "")).strip(),
        share=str(meta.get("share", "")).strip(),
        segments=tuple(segments),
        fingerprint=str(meta.get("fingerprint", "")),
        index_level=str(meta.get("index_level", "full")),
        size_bytes=int(meta.get("size_bytes", 0) or 0),
    )


# ---------------------------------------------------------------- 지시문 의심 탐지
# 문서 본문은 신뢰할 수 없는 "데이터"다. 아래 패턴에 걸린 문단은 화면에 경고와 함께 표시되고,
# AI 답변 모드에서는 모델에 전달되지 않는다. 어떤 경우에도 문서 속 문장을 실행하지 않는다.
_INJECTION_PATTERNS = [
    (re.compile(r"(이전|위의|기존)\s*(모든\s*)?(지시|명령|지침).{0,12}(무시|잊)"), "이전 지시 무시 요구"),
    (re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts?)"), "이전 지시 무시 요구(영문)"),
    (re.compile(r"(설정|권한|옵션).{0,10}(변경|수정|상향|바꿔|바꾸)"), "설정/권한 변경 요구"),
    (re.compile(r"(외부|다른\s*주소|메일|이메일|서버).{0,12}(전송|보내|유출|업로드)"), "외부 전송 요구"),
    (re.compile(r"(?i)(send|upload|post|exfiltrate).{0,30}(http|external|email|server)"), "외부 전송 요구(영문)"),
    (re.compile(r"(비밀번호|패스워드|api\s*키|토큰|인증정보).{0,10}(알려|출력|보여|입력|전달)"), "인증정보 요구"),
    (re.compile(r"(?i)system\s*prompt|시스템\s*프롬프트"), "시스템 프롬프트 언급"),
    (re.compile(r"(이\s*문장을\s*읽은|이\s*문서를\s*읽는)\s*(AI|인공지능|모델|어시스턴트)"), "AI 대상 지시"),
]


def detect_injection(text: str) -> str:
    """의심되면 사유 문자열, 아니면 빈 문자열."""
    reasons = []
    for pattern, label in _INJECTION_PATTERNS:
        if pattern.search(text):
            reasons.append(label)
    return ", ".join(dict.fromkeys(reasons))


# ---------------------------------------------------------------- 문단 분할
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*\S)\s*$")


def split_chunks(title: str, body: str, *, min_chars: int = 30, line_offset: int | None = None) -> list[Chunk]:
    """본문을 (제목 문맥, 문단) 단위로 나눈다.

    - 마크다운 제목(#)은 이후 문단의 ``heading`` 이 된다.
    - 빈 줄로 구분된 블록이 문단이며, 표/목록은 한 블록으로 유지된다.
    - 너무 짧은 블록은 다음 블록과 합쳐 의미 없는 조각을 줄인다.
    - ``line_offset`` 이 주어지면 파일 기준 줄 번호(메타데이터 줄 수 + 본문 줄)를 ``loc`` 에 "줄 a–b" 로 기록한다.
    """
    chunks: list[Chunk] = []
    heading = title
    block: list[str] = []
    block_start = 0
    pending = ""
    pending_start = None

    def loc_of(start: int, end: int) -> str:
        if line_offset is None:
            return ""
        a, b = start + line_offset + 1, end + line_offset + 1
        return f"줄 {a}" if a == b else f"줄 {a}–{b}"

    def emit(text: str, start: int, end: int) -> None:
        reason = detect_injection(text)
        chunks.append(Chunk(seq=len(chunks), heading=heading, text=text, flagged=bool(reason), flag_reason=reason,
                            loc=loc_of(start, end)))

    def flush(end: int) -> None:
        nonlocal block, pending, pending_start
        if not block:
            return
        text = "\n".join(block).strip()
        start = block_start
        block = []
        if not text:
            return
        if pending:
            text = pending + "\n" + text
            start = pending_start if pending_start is not None else start
            pending, pending_start = "", None
        if len(text) < min_chars:
            pending, pending_start = text, start
            return
        emit(text, start, end)

    lines = body.splitlines()
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            flush(i - 1)
            if pending:  # 제목 직전 남은 짧은 블록은 독립 문단으로 확정
                emit(pending, pending_start or 0, i - 1)
                pending, pending_start = "", None
            heading = m.group(2)
            continue
        if not line.strip():
            flush(i - 1)
        else:
            if not block:
                block_start = i
            block.append(line.rstrip())
    flush(len(lines) - 1)
    if pending:
        emit(pending, pending_start or 0, len(lines) - 1)
    return chunks
