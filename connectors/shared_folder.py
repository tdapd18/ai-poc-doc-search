"""가상 공유폴더 Connector (data/shared_folder).

- 등록부(ShareRegistry)가 있으면 등록된 **여러 공유**(UNC 경로 ↔ 가상 폴더)를 모두 읽는다 (다중 경로 검색).
  등록부가 없으면 기존 방식(루트 폴더 하나)으로 동작한다.
- 지원 형식: .md/.txt (본문 첫머리의 ``---`` 메타데이터), .pdf/.xlsx/.pptx (옆의 ``<파일명>.meta.json`` 메타데이터).
- 문서 위치: md/txt 는 줄 번호, pdf 는 페이지, xlsx 는 시트·셀 범위, pptx 는 슬라이드.
- 결과의 원본 위치는 UNC 경로(``unc_root`` + 공유 내부 상대 경로, 구분자 ``\\``)로 표시한다.
실제 SMB 접속은 구현하지 않았다(로그인/프로토콜 규격 미확인). 실제 연동 시 이 클래스의 파일 열거/읽기 부분만 교체한다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from connectors.base import BaseConnector, ConnectorError
from core.document_parser import parse_front_matter_ex, split_chunks, to_common_document
from core.extractors import EXTRACTORS
from core.models import FetchResult, InvalidDocumentError, InvalidItem, Segment
from core.shares import Share, ShareRegistry

TEXT_SUFFIXES = {".md", ".txt"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | set("." + k for k in EXTRACTORS)
MAX_TEXT_BYTES = 1_000_000
MAX_BINARY_BYTES = 20_000_000
LEGACY_SHARE = Share("공유폴더", "\\\\fileserver.example.invalid\\공유폴더", "", True)


@dataclass(frozen=True)
class FileEntry:
    rel_path: str
    size: int
    mtime_ns: int
    sha256: str


class SharedFolderConnector(BaseConnector):
    source_key = "shared_folder"
    source_label = "공유폴더"

    def __init__(self, root: Path | str, registry: ShareRegistry | None = None):
        super().__init__(root)
        self.registry = registry

    # -- 공유 목록 ----------------------------------------------------------
    def shares(self) -> list[Share]:
        return self.registry.enabled() if self.registry else [LEGACY_SHARE]

    def health_check(self) -> None:
        if not self.root.is_dir():
            raise ConnectorError("공유폴더에 접근할 수 없습니다 (경로 없음)")

    def _share_root(self, share: Share) -> Path:
        return (self.root / share.local_dir).resolve() if share.local_dir else self.root.resolve()

    # -- 파일 탐색 ----------------------------------------------------------
    def _iter_files(self):
        """(파일, 공유, 공유 루트) 를 재귀적으로 열거한다. 루트 밖을 가리키는 링크와 임시/숨김 파일은 제외."""
        top = self.root.resolve()
        for share in self.shares():
            sroot = self._share_root(share)
            try:
                sroot.relative_to(top)
            except ValueError:
                continue
            if not sroot.is_dir():
                yield None, share, sroot
                continue
            for path in sorted(sroot.rglob("*")):
                name = path.name
                if (not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES
                        or name.startswith(("~$", "."))):
                    continue
                try:
                    path.resolve().relative_to(sroot)
                except ValueError:
                    continue
                yield path, share, sroot

    def scan(self) -> dict[str, FileEntry]:
        """파일명(상대경로)·크기·수정시각·해시를 수집한다."""
        self.health_check()
        entries: dict[str, FileEntry] = {}
        top = self.root.resolve()
        for path, _share, _sroot in self._iter_files():
            if path is None:
                continue
            try:
                stat = path.stat()
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue  # 스캔 중 삭제/잠금 → 다음 스캔에서 반영
            rel = path.relative_to(top).as_posix()
            entries[rel] = FileEntry(rel, stat.st_size, stat.st_mtime_ns, digest)
        return entries

    @staticmethod
    def detect_changes(previous: dict[str, FileEntry], current: dict[str, FileEntry]) -> dict[str, list[str]]:
        """이전 스캔 대비 신규/변경/삭제 파일을 반환한다."""
        new = sorted(set(current) - set(previous))
        removed = sorted(set(previous) - set(current))
        changed = sorted(p for p in set(current) & set(previous) if current[p].sha256 != previous[p].sha256)
        return {"new": new, "changed": changed, "removed": removed}

    @staticmethod
    def unc_path(share: Share, rel_in_share: str) -> str:
        return share.unc_root.rstrip("\\") + "\\" + rel_in_share.replace("/", "\\")

    # -- 문서 수집 ----------------------------------------------------------
    def fetch_all(self) -> FetchResult:
        self.health_check()
        result = FetchResult()
        for path, share, sroot in self._iter_files():
            if path is None:
                result.invalid.append(InvalidItem(share.name, "공유폴더에 접근할 수 없습니다 (경로 없음)"))
                continue
            rel = path.relative_to(sroot).as_posix()
            origin = f"{share.name}/{rel}" if self.registry else rel
            try:
                doc = self._read(path, share, rel)
            except InvalidDocumentError as exc:
                result.invalid.append(InvalidItem(origin, str(exc)))
                continue
            except UnicodeDecodeError:
                result.invalid.append(InvalidItem(origin, "UTF-8 인코딩이 아닙니다"))
                continue
            except OSError:
                result.invalid.append(InvalidItem(origin, "파일을 읽을 수 없습니다 (삭제/잠금)"))
                continue
            self._add_unique(result, doc, origin)
        return result

    def _read(self, path: Path, share: Share, rel: str):
        suffix = path.suffix.lower()
        common = {"file_name": path.name, "share": share.name,
                  "location": self.unc_path(share, rel), "location_detail": f"{share.name} / {rel}"}
        size = path.stat().st_size
        if suffix in TEXT_SUFFIXES:
            if size > MAX_TEXT_BYTES:
                raise InvalidDocumentError("파일 크기 제한 초과")
            meta, body, offset = parse_front_matter_ex(path.read_text(encoding="utf-8"))
            meta.update(common, file_type=suffix[1:])
            segs: tuple[Segment, ...] = tuple(
                (c.heading, c.loc, c.text) for c in split_chunks(str(meta.get("title", "")), body, line_offset=offset))
            return to_common_document(meta, body, source_key=self.source_key, source_system=self.source_label,
                                      segments=segs)
        if size > MAX_BINARY_BYTES:
            raise InvalidDocumentError("파일 크기 제한 초과")
        sidecar = Path(str(path) + ".meta.json")
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise InvalidDocumentError("메타데이터 파일(.meta.json)이 없습니다") from None
        except json.JSONDecodeError:
            raise InvalidDocumentError("메타데이터 파일(.meta.json) 형식 오류") from None
        if not isinstance(meta, dict):
            raise InvalidDocumentError("메타데이터 파일(.meta.json) 형식 오류")
        meta.update(common, file_type=suffix[1:])
        segs = tuple(EXTRACTORS[suffix[1:]](path))
        body = "\n\n".join(t for _, _, t in segs)
        return to_common_document(meta, body, source_key=self.source_key, source_system=self.source_label,
                                  segments=segs)
