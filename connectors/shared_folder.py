"""공유폴더 Connector — 가상 공유(데모)와 **실제 Windows UNC 공유**를 같은 코드로 읽는다.

공유 종류 (core/shares.py)
- virtual : 데모. UNC 경로는 표시용이고 data/shared_folder 아래 가상 폴더를 읽는다. 메타데이터는 머리말/.meta.json 필수(엄격).
- unc     : 실제 UNC 경로를 ``FileSystem``(기본 LocalFS = OS 파일 API)로 읽는다. ``.meta.json`` 없이 **자동 메타데이터**.
            로그인한 Windows 계정으로 열 수 있는 파일만 색인된다(운영 체제가 권한을 판정).

색인 수준 (core/app_config.py)
- metadata_only : 이름·경로·형식·수정일·크기만. **파일 내용을 읽지 않는다**(권한 확인을 위해 열기만 시도).
- full_text     : 본문 추출 (보안 승인 기록 필요). 추출 불가 형식·한도 초과 파일은 메타데이터 수준으로 색인한다.

증분 수집: 자동 ID 문서는 (크기:수정시각) 지문이 같으면 다시 읽지 않는다. 단, **권한은 매번 파일 열기로 재확인**한다
(ACL 변경은 수정 시각을 바꾸지 않기 때문).

오류 분류 (core/fs.py): 접근 거부 → 색인에서 제거(fail-closed) / 일시 오류(잠금·네트워크) → 기존 색인 유지 후 재시도 /
공유 접근 불가·부분 수집 → 그 공유의 삭제 판단을 하지 않음. 결과에는 파일 이름 대신 **건수**만 보고한다.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from connectors.base import BaseConnector, ConnectorError
from core.app_config import AppConfig, demo_config
from core.document_parser import parse_front_matter_ex, split_chunks, to_common_document
from core.extractors import EXTRACTABLE, decode_text, extract
from core.fs import (FileSystem, FsAccessDenied, FsEntry, FsError, FsNotFound, FsUnavailable, LocalFS, MappedFS,
                     unc_join, unc_key, unc_relative)
from core.metadata import derive_metadata, load_category_rules
from core.models import FetchResult, InvalidDocumentError, InvalidItem, Segment
from core.shares import Share, ShareRegistry

TEXT_EXT = {"md", "txt"}
LEGACY_EXT = {"doc": "doc", "xls": "xls", "ppt": "ppt", "hwp": "hwp", "hwpx": "hwp"}  # 본문 추출 미지원(파일명 검색만)
EXT_ALIAS = {"xlsm": "xlsx"}
SUPPORTED_SUFFIXES = {"." + e for e in TEXT_EXT | EXTRACTABLE | set(EXT_ALIAS)}
LEGACY_SHARE = Share("공유폴더", "\\\\fileserver.example.invalid\\공유폴더", "", True)
PROGRESS_EVERY = 25


@dataclass(frozen=True)
class FileEntry:
    rel_path: str
    size: int
    mtime_ns: int
    sha256: str


class SharedFolderConnector(BaseConnector):
    source_key = "shared_folder"
    source_label = "공유폴더"

    def __init__(self, root: Path | str, registry: ShareRegistry | None = None, *,
                 fs_factory: Callable[[Share], FileSystem] | None = None, config: AppConfig | None = None,
                 rules: dict | Path | str | None = None):
        super().__init__(root)
        self.registry = registry
        self.fs_factory = fs_factory
        self.config = config or demo_config()
        self.rules = rules if isinstance(rules, dict) else load_category_rules(rules)
        self.progress: Callable[[dict], None] | None = None
        self._virtual_fs: dict[str, MappedFS] = {}

    # -- 공유/파일시스템 -----------------------------------------------------
    def shares(self) -> list[Share]:
        return self.registry.enabled() if self.registry else [LEGACY_SHARE]

    def health_check(self) -> None:
        if not self.root.is_dir() and any(s.kind == "virtual" for s in self.shares()):
            raise ConnectorError("공유폴더에 접근할 수 없습니다 (경로 없음)")

    def _share_root(self, share: Share) -> Path:
        return (self.root / share.local_dir).resolve() if share.local_dir else self.root.resolve()

    def fs_for(self, share: Share) -> FileSystem:
        if share.kind == "virtual":
            if share.name not in self._virtual_fs:
                self._virtual_fs[share.name] = MappedFS({share.unc_root: self._share_root(share)})
            return self._virtual_fs[share.name]
        return self.fs_factory(share) if self.fs_factory else LocalFS()

    def fs_for_share_name(self, name: str) -> FileSystem:
        for s in self.shares() if self.registry is None else self.registry.list():
            if s.name == name:
                return self.fs_for(s)
        return self.fs_factory(Share(name, "", kind="unc")) if self.fs_factory else LocalFS()

    # -- (구) 변경 감지 도우미: 가상 공유 전용, 기존 테스트/도구 호환 ---------------
    def _iter_files(self):
        top = self.root.resolve()
        for share in self.shares():
            if share.kind != "virtual":
                continue
            sroot = self._share_root(share)
            if not sroot.is_dir():
                yield None, share, sroot
                continue
            for path in sorted(sroot.rglob("*")):
                if (not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES
                        or path.name.startswith(("~$", "."))):
                    continue
                try:
                    path.resolve().relative_to(sroot)
                except ValueError:
                    continue
                yield path, share, sroot

    def scan(self) -> dict[str, FileEntry]:
        """파일명(상대경로)·크기·수정시각·해시를 수집한다 (가상 공유)."""
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
                continue
            rel = path.relative_to(top).as_posix()
            entries[rel] = FileEntry(rel, stat.st_size, stat.st_mtime_ns, digest)
        return entries

    @staticmethod
    def detect_changes(previous: dict[str, FileEntry], current: dict[str, FileEntry]) -> dict[str, list[str]]:
        new = sorted(set(current) - set(previous))
        removed = sorted(set(previous) - set(current))
        changed = sorted(p for p in set(current) & set(previous) if current[p].sha256 != previous[p].sha256)
        return {"new": new, "changed": changed, "removed": removed}

    @staticmethod
    def unc_path(share: Share, rel_in_share: str) -> str:
        return share.unc_root.rstrip("\\") + "\\" + rel_in_share.replace("/", "\\")

    # -- 수집 -----------------------------------------------------------------
    def fetch_all(self) -> FetchResult:
        return self.fetch_incremental({})

    def _excluded(self, name: str, share: Share) -> bool:
        n = name.casefold()
        if name.startswith("."):
            return True
        return any(fnmatch.fnmatch(n, p.casefold()) for p in (*self.config.exclude_patterns, *share.exclude))

    def fetch_incremental(self, snapshot: dict[str, dict]) -> FetchResult:
        self.health_check()
        result = FetchResult()
        by_path = {unc_key(row.get("location", "")): (did, row) for did, row in snapshot.items() if row.get("location")}
        for share in self.shares():
            self._fetch_share(share, snapshot, by_path, result)
        return result

    def _fetch_share(self, share: Share, snapshot: dict[str, dict], by_path: dict, result: FetchResult) -> None:
        fs = self.fs_for(share)
        strict = share.kind == "virtual"
        cfg = self.config
        counters = {"files": 0, "indexed": 0}
        failed_dirs: list[str] = []
        stack: list[tuple[str, int]] = [(share.unc_root, 0)]
        root_checked = False
        while stack:
            path, depth = stack.pop()
            try:
                entries = fs.scandir(path)
            except FsAccessDenied:
                if not root_checked:
                    result.denied += 1
                    result.invalid.append(InvalidItem(share.name, "이 계정으로는 공유에 접근할 수 없습니다 (권한 없음)"))
                    root_checked = True
                    continue
                result.denied += 1  # 접근할 수 없는 하위 폴더: 그 아래 문서는 색인에서 제거(fail-closed)
                continue
            except (FsNotFound, FsUnavailable) as exc:
                if not root_checked:
                    result.invalid.append(InvalidItem(share.name, "공유폴더에 접근할 수 없습니다 (경로 없음)" if isinstance(exc, FsNotFound)
                                                      else "공유폴더에 연결할 수 없습니다 (네트워크 확인)"))
                    if not strict:  # 실제 공유: 일시 장애로 색인을 지우지 않는다
                        result.unavailable_shares.append(share.name)
                        result.no_delete_shares.add(share.name)
                    root_checked = True
                    continue
                failed_dirs.append(path)  # 하위 폴더 일시 오류 → 그 아래 문서는 삭제 판단 보류
                result.warnings.append("일부 폴더를 읽지 못했습니다 (다음 색인 때 재시도)")
                continue
            root_checked = True
            names_here = {e.name.casefold(): e for e in entries}
            files = []
            for e in sorted(entries, key=lambda x: x.name.casefold(), reverse=True):
                if self._excluded(e.name, share) or e.is_link:
                    continue
                if e.is_dir:
                    if depth < cfg.max_depth:
                        stack.append((e.path, depth + 1))
                    else:
                        result.skip("폴더 깊이 한도 초과")
                else:
                    files.append(e)
            for e in reversed(files):
                if counters["files"] >= cfg.max_files_per_share:
                    result.no_delete_shares.add(share.name)
                    result.warnings.append(f"공유 '{share.name}' 은(는) 파일 수 한도({cfg.max_files_per_share})까지만 색인했습니다")
                    stack.clear()
                    break
                counters["files"] += 1
                result.scanned += 1
                self._file(fs, share, e, names_here, by_path, result, strict)
                if self.progress and counters["files"] % PROGRESS_EVERY == 0:
                    self.progress({"share": share.name, "files": counters["files"], "documents": len(result.documents)})
        # 하위 폴더 일시 오류: 그 아래 기존 문서는 유지(삭제 판단 보류)
        for d in failed_dirs:
            prefix = unc_key(d) + "\\"
            for did, row in snapshot.items():
                if row.get("share") == share.name and unc_key(row.get("location", "")).startswith(prefix):
                    result.retained_ids.add(did)
        if self.progress:
            self.progress({"share": share.name, "files": counters["files"], "documents": len(result.documents), "done": True})

    # -- 파일 하나 ------------------------------------------------------------
    def _file(self, fs: FileSystem, share: Share, e: FsEntry, names_here: dict[str, FsEntry], by_path: dict,
              result: FetchResult, strict: bool) -> None:
        name = e.name
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if name.lower().endswith(".meta.json"):
            return
        ext = EXT_ALIAS.get(ext, ext)
        kind = "text" if ext in TEXT_EXT else "extract" if ext in EXTRACTABLE else "legacy" if (ext in LEGACY_EXT and not strict) else None
        if kind is None:
            result.skip("지원하지 않는 형식")
            return
        cfg = self.config
        rel = unc_relative(share.unc_root, e.path)
        rel_fwd = rel.replace("\\", "/")
        origin = f"{share.name}/{rel_fwd}" if self.registry else rel_fwd
        fingerprint = f"{e.size}:{e.mtime_ns}"
        side_entry = names_here.get(f"{name}.meta.json".casefold())
        if side_entry is not None:  # 메타데이터 파일(.meta.json)만 바뀌어도(예: 권한 변경) 다시 읽도록 지문에 포함
            fingerprint += f"|{side_entry.size}:{side_entry.mtime_ns}"
        file_type = LEGACY_EXT.get(ext, ext)
        want_full = strict or (cfg.index_mode == "full_text" and cfg.approval.approved)
        level = "full" if (want_full and kind in ("text", "extract")) else "metadata"
        if level == "full" and e.size > cfg.max_file_mb * 1024 * 1024:
            level = "metadata"
            result.skip(f"크기 한도({cfg.max_file_mb}MB) 초과 — 파일명 검색만")
        elif kind == "legacy" and want_full:
            result.skip("구형/미지원 형식 — 파일명 검색만")

        from core.metadata import auto_doc_id
        doc_id, prev = by_path.get(unc_key(e.path), (None, None))
        if doc_id is None and not strict:
            doc_id = auto_doc_id(e.path)
        try:
            # --- 권한/접근 확인 (메타 전용에서도 '열기만' 시도 — 내용은 읽지 않는다)
            if prev is not None and prev.get("fingerprint") == fingerprint and prev.get("index_level") == level \
                    and prev.get("share") == share.name:
                fs.check_open(e.path)  # 변경 없음: 다시 읽지 않되 권한은 재확인
                result.unchanged_ids.add(doc_id)
                return
            if level == "metadata":
                if cfg.verify_open_in_metadata_mode or not strict:
                    fs.check_open(e.path)
                doc = self._build(share, e, rel, ext, file_type, fingerprint, level, b"", names_here, fs, strict)
            else:
                data = fs.read_bytes(e.path, cfg.max_file_mb * 1024 * 1024)
                try:
                    after = fs.stat(e.path)
                except FsError:
                    after = None
                if after is not None and after.fingerprint != fingerprint.split("|")[0]:  # 사이드카 부분 제외, 파일 자체 지문만 비교
                    raise FsUnavailable("읽는 중 파일이 변경되었습니다")
                doc = self._build(share, e, rel, ext, file_type, fingerprint, level, data, names_here, fs, strict, result)
        except FsAccessDenied:
            result.denied += 1  # 이 계정이 읽을 수 없음 → 색인에서 제거(fail-closed). 파일 이름은 보고하지 않는다
            return
        except FsNotFound:
            return  # 목록 조회 후 삭제됨 → 다음 색인에서 반영
        except FsUnavailable:
            if doc_id and prev is not None:
                result.retained_ids.add(doc_id)  # 일시 오류: 기존 색인 유지, 조회 시에는 OS 재검증으로 숨김
            result.skip("일시적으로 읽지 못함(잠금/네트워크) — 다음 색인 때 재시도")
            return
        except InvalidDocumentError as exc:
            result.invalid.append(InvalidItem(origin, str(exc)))
            return
        self._add_unique(result, doc, origin)

    def _build(self, share: Share, e: FsEntry, rel: str, ext: str, file_type: str, fingerprint: str, level: str,
               data: bytes, names_here: dict[str, FsEntry], fs: FileSystem, strict: bool, result: FetchResult | None = None):
        from core.metadata import derive_metadata
        if strict:  # 데모 가상 공유: 머리말/.meta.json 에 명시된 메타데이터만 인정 (누락은 형식 오류)
            meta = {"location": e.path, "file_name": e.name, "share": share.name}
        else:
            meta = derive_metadata(unc_path=e.path, rel_in_share=rel, file_name=e.name, share_name=share.name,
                                   mtime_ns=e.mtime_ns, created_ns=e.created_ns or e.mtime_ns, rules=self.rules)
        meta.update(file_type=file_type, fingerprint=fingerprint, index_level=level, size_bytes=e.size)
        meta["location_detail"] = f"{share.name} / {rel.replace(chr(92), ' / ')}"
        segments: tuple[Segment, ...] = ()
        body = ""
        side = f"{e.name}.meta.json".casefold()
        sidecar_present = side in names_here
        side_meta: dict | None = None
        if sidecar_present:  # 잘못된 메타데이터 파일은 본문 추출 전에 먼저 보고한다
            try:
                side_meta = json.loads(fs.read_bytes(unc_join(unc_relative_parent(e.path), f"{e.name}.meta.json"), 1_000_000).decode("utf-8"))
            except FsAccessDenied:
                raise
            except (FsError, UnicodeDecodeError, json.JSONDecodeError):
                raise InvalidDocumentError("메타데이터 파일(.meta.json) 형식 오류") from None
            if not isinstance(side_meta, dict):
                raise InvalidDocumentError("메타데이터 파일(.meta.json) 형식 오류")
        if level == "full":
            if ext in TEXT_EXT:
                text, enc = decode_text(data)
                if enc == "utf-8(replace)":
                    raise InvalidDocumentError("텍스트 인코딩을 판별할 수 없습니다 (UTF-8/CP949 아님)")
                try:
                    fm, body, offset = parse_front_matter_ex(text)
                    meta.update({k: v for k, v in fm.items() if k not in ("location", "location_detail", "share", "file_name")})
                    base = offset
                except InvalidDocumentError:
                    if strict:
                        raise
                    body, base = text.strip("\n"), 0
                    if not body.strip():
                        raise InvalidDocumentError("본문이 비어 있습니다") from None
                segments = tuple((c.heading, c.loc, c.text)
                                 for c in split_chunks(str(meta.get("title", "")), body, line_offset=base))
            else:
                if strict and not sidecar_present:
                    raise InvalidDocumentError("메타데이터 파일(.meta.json)이 없습니다")
                ex = extract(ext, data)
                segments = tuple(ex.segments)
                body = "\n\n".join(t for _, _, t in segments)
                if ex.props.get("title") and len(ex.props["title"]) >= 2:
                    meta["title"] = ex.props["title"]
                if result is not None:
                    for w in ex.warnings:
                        result.warnings.append(w)
        elif strict and not sidecar_present and ext not in TEXT_EXT:
            raise InvalidDocumentError("메타데이터 파일(.meta.json)이 없습니다")
        if side_meta:
            meta.update({k: v for k, v in side_meta.items() if k not in ("location", "location_detail", "share", "file_name",
                                                                         "fingerprint", "index_level", "file_type")})
        return to_common_document(meta, body, source_key=self.source_key, source_system=self.source_label,
                                  segments=segments, allow_empty_body=(level == "metadata"))


def unc_relative_parent(path: str) -> str:
    from core.fs import unc_parent
    return unc_parent(path)
