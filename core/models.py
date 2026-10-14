"""공통 데이터 구조.

모든 Connector가 수집한 자료는 이 모듈의 ``Document`` 로 변환되어 색인/검색 엔진에 전달된다.
검색 엔진은 저장소별 구현(SMB, 그룹웨어 API 등)을 알지 못한다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

CATEGORIES = ("IFRS17", "RAFM", "결산", "기타")

# 문서 유형(파일 형식) 표시명. 공유폴더는 실제 파일 확장자, 그룹웨어/업무시스템은 자체 유형.
FILE_TYPES = {
    "md": "Markdown", "txt": "텍스트", "pdf": "PDF", "xlsx": "Excel", "pptx": "PowerPoint", "docx": "Word", "csv": "CSV",
    "post": "게시글", "record": "업무시스템 레코드",
    # 본문 추출을 지원하지 않는 형식(파일명·경로 검색만 가능)
    "doc": "Word(구형)", "xls": "Excel(구형)", "ppt": "PowerPoint(구형)", "hwp": "한글", "other": "기타 파일",
}
FILE_TYPE_SHORT = {"md": "MD", "txt": "TXT", "pdf": "PDF", "xlsx": "XLSX", "pptx": "PPTX", "docx": "DOCX", "csv": "CSV",
                   "post": "게시글", "record": "레코드", "doc": "DOC", "xls": "XLS", "ppt": "PPT", "hwp": "HWP",
                   "other": "파일"}
INDEX_LEVELS = ("full", "metadata")  # full: 본문 색인 / metadata: 파일명·경로·형식·수정일만

# 문서 안의 한 조각: (소제목/시트/슬라이드 제목, 위치 표기, 텍스트)
Segment = tuple[str, str, str]


class InvalidDocumentError(ValueError):
    """문서 형식 오류. 메시지에는 필드명/사유만 담고 문서 본문은 절대 포함하지 않는다."""


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    source_key: str  # 예: shared_folder
    source_system: str  # 예: 공유폴더
    category: str
    version: str
    created_at: str  # YYYY-MM-DD
    modified_at: str  # YYYY-MM-DD
    department: str
    location: str  # 원본 위치 또는 가상 URL
    body: str
    allowed_users: tuple[str, ...] = ()
    allowed_groups: tuple[str, ...] = ()
    location_detail: str = ""  # 폴더 경로 / 게시판 / 업무시스템 화면 경로 등
    attachments: tuple[str, ...] = ()
    file_type: str = "md"  # FILE_TYPES 의 키
    file_name: str = ""  # 파일명(공유폴더) — 파일명 검색 대상
    share: str = ""  # 등록된 공유폴더 표시 이름 (공유폴더 문서만)
    segments: tuple[Segment, ...] = ()  # 형식별 위치(페이지/시트·셀/슬라이드/줄)를 보존한 조각. 없으면 본문에서 분할
    fingerprint: str = ""  # 원본 파일 지문(크기:수정시각) — 증분 수집용. 내용 해시에는 포함하지 않는다
    index_level: str = "full"  # full | metadata
    size_bytes: int = 0

    def content_hash(self) -> str:
        """본문·메타데이터 해시 (접근권한 제외). 수정/버전 변경 감지용."""
        payload = json.dumps(
            [self.title, self.category, self.version, self.created_at, self.modified_at,
             self.department, self.location, self.location_detail, list(self.attachments), self.body,
             self.file_type, self.file_name, self.share, [list(x) for x in self.segments], self.index_level],
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def acl_hash(self) -> str:
        """접근권한 해시. 권한 변경 감지용."""
        payload = json.dumps(
            [sorted(self.allowed_users), sorted(self.allowed_groups)], ensure_ascii=False
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Chunk:
    seq: int
    heading: str
    text: str
    flagged: bool = False  # 지시문 의심 문장 포함 여부
    flag_reason: str = ""
    loc: str = ""  # 원문 위치: "p.2" / "시트 '요약' · 셀 A5:D5" / "슬라이드 3" / "줄 12–18"


@dataclass(frozen=True)
class InvalidItem:
    """수집 실패/형식 오류 항목. 위치와 사유만 보관한다(본문 금지)."""

    path: str
    reason: str


@dataclass
class FetchResult:
    documents: list[Document] = field(default_factory=list)
    invalid: list[InvalidItem] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)  # 중복 ID 목록
    # --- 증분 수집 / 안전한 변경 처리용 (파일 이름은 담지 않고 건수·ID 만) ---
    unchanged_ids: set[str] = field(default_factory=set)  # 지문이 같아 다시 읽지 않은 문서
    retained_ids: set[str] = field(default_factory=set)  # 일시 오류(잠금/네트워크)로 확인 못 해 기존 색인을 유지할 문서
    no_delete_shares: set[str] = field(default_factory=set)  # 접근 불가·부분 수집으로 '삭제 판단'을 하지 않을 공유 이름
    unavailable_shares: list[str] = field(default_factory=list)
    denied: int = 0  # 읽기 권한이 없어 색인하지 않은 파일/폴더 수
    skipped: dict[str, int] = field(default_factory=dict)  # 사유별 건수
    warnings: list[str] = field(default_factory=list)
    scanned: int = 0

    def skip(self, reason: str, n: int = 1) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + n
