"""가상 공유폴더 Connector (data/shared_folder). 하위 폴더를 재귀 탐색하며 .md/.txt 를 읽는다."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from connectors.base import BaseConnector, ConnectorError
from core.document_parser import parse_front_matter, to_common_document
from core.models import FetchResult, InvalidDocumentError, InvalidItem

SUPPORTED_SUFFIXES = {".md", ".txt"}
MAX_FILE_BYTES = 1_000_000


@dataclass(frozen=True)
class FileEntry:
    rel_path: str
    size: int
    mtime_ns: int
    sha256: str


class SharedFolderConnector(BaseConnector):
    source_key = "shared_folder"
    source_label = "공유폴더"

    def health_check(self) -> None:
        if not self.root.is_dir():
            raise ConnectorError("공유폴더에 접근할 수 없습니다 (경로 없음)")

    # -- 파일 탐색 ----------------------------------------------------------
    def _iter_files(self):
        root = self.root.resolve()
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            try:
                path.resolve().relative_to(root)  # 심볼릭 링크 등으로 루트 밖을 읽는 것을 방지
            except ValueError:
                continue
            yield path, root

    def scan(self) -> dict[str, FileEntry]:
        """파일명(상대경로)·크기·수정시각·해시를 수집한다."""
        self.health_check()
        entries: dict[str, FileEntry] = {}
        for path, root in self._iter_files():
            try:
                stat = path.stat()
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue  # 스캔 중 삭제/잠금 → 다음 스캔에서 반영
            rel = path.relative_to(root).as_posix()
            entries[rel] = FileEntry(rel, stat.st_size, stat.st_mtime_ns, digest)
        return entries

    @staticmethod
    def detect_changes(previous: dict[str, FileEntry], current: dict[str, FileEntry]) -> dict[str, list[str]]:
        """이전 스캔 대비 신규/변경/삭제 파일을 반환한다."""
        new = sorted(set(current) - set(previous))
        removed = sorted(set(previous) - set(current))
        changed = sorted(p for p in set(current) & set(previous) if current[p].sha256 != previous[p].sha256)
        return {"new": new, "changed": changed, "removed": removed}

    # -- 문서 수집 ----------------------------------------------------------
    def fetch_all(self) -> FetchResult:
        self.health_check()
        result = FetchResult()
        for path, root in self._iter_files():
            rel = path.relative_to(root).as_posix()
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    raise InvalidDocumentError("파일 크기 제한 초과")
                text = path.read_text(encoding="utf-8")
                meta, body = parse_front_matter(text)
                meta.setdefault("location_detail", f"공유폴더 / {rel}")
                doc = to_common_document(
                    meta, body, source_key=self.source_key, source_system=self.source_label
                )
            except InvalidDocumentError as exc:
                result.invalid.append(InvalidItem(rel, str(exc)))
                continue
            except UnicodeDecodeError:
                result.invalid.append(InvalidItem(rel, "UTF-8 인코딩이 아닙니다"))
                continue
            except OSError:
                result.invalid.append(InvalidItem(rel, "파일을 읽을 수 없습니다 (삭제/잠금)"))
                continue
            self._add_unique(result, doc, rel)
        return result
