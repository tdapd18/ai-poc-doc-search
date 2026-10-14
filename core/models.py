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
    "md": "Markdown", "txt": "텍스트", "pdf": "PDF", "xlsx": "Excel", "pptx": "PowerPoint",
    "post": "게시글", "record": "업무시스템 레코드",
}
FILE_TYPE_SHORT = {"md": "MD", "txt": "TXT", "pdf": "PDF", "xlsx": "XLSX", "pptx": "PPTX", "post": "게시글",
                   "record": "레코드"}

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

    def content_hash(self) -> str:
        """본문·메타데이터 해시 (접근권한 제외). 수정/버전 변경 감지용."""
        payload = json.dumps(
            [self.title, self.category, self.version, self.created_at, self.modified_at,
             self.department, self.location, self.location_detail, list(self.attachments), self.body,
             self.file_type, self.file_name, self.share, [list(x) for x in self.segments]],
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
