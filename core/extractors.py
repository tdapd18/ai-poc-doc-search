"""파일 형식별 본문 추출 (표준 라이브러리만 사용).

공개 API
  extract(ext, data: bytes) -> Extracted(segments, props, warnings)   # ext: 'pdf'|'docx'|'xlsx'|'pptx'|'csv'
  extract_pdf / extract_docx / extract_xlsx / extract_pptx / extract_csv (Path 또는 bytes) -> list[Segment]
  decode_text(data) -> (text, encoding)                               # UTF-8/BOM/UTF-16/CP949 판별

Segment = (소제목, 위치 표기, 텍스트). 위치 표기:
  pdf  : "p.2"                        docx : "문단 12–15 · 약 3쪽" / "표 2 · 행 3"
  xlsx : "시트 '요약' · 셀 A5:D5"       pptx : "슬라이드 3" / "슬라이드 4 (숨김)"
  csv  : "행 5" (대용량은 "행 21–30")

오류 처리: 손상·암호화·구형(OLE)·지원하지 않는 파일은 ``InvalidDocumentError``(본문 미포함 메시지).
압축 폭탄 방지(항목 수·해제 크기), XML DTD/ENTITY 거부, 행·열·페이지 수 상한.

!! 한계 !! (실제 업무문서 검증 전 — docs/WINDOWS_SHARE_PLAN.md §5 미검증 항목)
- PDF: 스캔본(OCR 필요), ToUnicode 없는 CID 글꼴(Identity-H), LZW/JBIG 등 특수 필터, 암호화 PDF 는 추출하지 못한다.
  Flate/ASCII85/ASCIIHex, 객체 스트림(ObjStm), ToUnicode CMap, WinAnsi 단일바이트 글꼴, UCS2 인코딩은 지원한다.
- DOCX: 쪽 번호는 Word 가 저장한 줄바꿈 표시(lastRenderedPageBreak) 기반의 **추정**이다.
- 구형 .doc/.xls/.ppt(OLE), 암호화 Office, .xlsb, .hwp 는 본문을 읽지 않고 파일명 검색만 지원한다.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from core.models import InvalidDocumentError, Segment

MAX_ZIP_MEMBERS = 2000
MAX_UNCOMPRESSED = 60 * 1024 * 1024
MAX_ROWS_PER_SHEET = 20000
MAX_COLS = 200
MAX_PDF_PAGES = 1000
MAX_CSV_ROWS = 50000
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
}


def _q(prefix: str, tag: str) -> str:
    return f"{{{_NS[prefix]}}}{tag}"


@dataclass
class Extracted:
    segments: list[Segment]
    props: dict = field(default_factory=dict)  # title, author, created, modified
    warnings: list[str] = field(default_factory=list)


def _bytes(src) -> bytes:
    if isinstance(src, (bytes, bytearray)):
        return bytes(src)
    try:
        return Path(src).read_bytes()
    except OSError:
        raise InvalidDocumentError("파일을 읽을 수 없습니다") from None


# ------------------------------------------------------------------ 텍스트 디코딩
def decode_text(data: bytes) -> tuple[str, str]:
    """BOM → UTF-8(엄격) → CP949(한국어 Windows 기본) 순으로 판별한다. 모두 실패하면 UTF-8 대체 문자."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace"), "utf-16"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp949"), "cp949"
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), "utf-8(replace)"


# ------------------------------------------------------------------ zip(OOXML) 공통
def _open_zip(data: bytes) -> zipfile.ZipFile:
    if data[:8] == OLE_MAGIC:
        raise InvalidDocumentError("암호로 보호된 파일이거나 구형(OLE) 형식입니다")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        raise InvalidDocumentError("손상되었거나 올바른 Office 파일이 아닙니다") from None
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_MEMBERS or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
        zf.close()
        raise InvalidDocumentError("파일 내부 크기 제한 초과")
    if any(i.flag_bits & 0x1 for i in infos):
        zf.close()
        raise InvalidDocumentError("암호화된 파일은 지원하지 않습니다")
    return zf


def _xml(zf: zipfile.ZipFile, name: str) -> ET.Element:
    try:
        data = zf.read(name)
    except KeyError:
        raise InvalidDocumentError(f"필수 구성요소 누락: {name}") from None
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:  # XML 엔티티 확장 공격 차단
        raise InvalidDocumentError("허용되지 않는 XML 구조(DTD/ENTITY)")
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        raise InvalidDocumentError("XML 구조 오류") from None


def _rels(zf: zipfile.ZipFile, base_dir: str, rels_name: str) -> dict[str, tuple[str, str]]:
    """relationship Id → (zip 내 경로, Type)."""
    out: dict[str, tuple[str, str]] = {}
    try:
        root = _xml(zf, rels_name)
    except InvalidDocumentError:
        return out
    for rel in root.findall("rel:Relationship", _NS):
        target = rel.get("Target", "")
        full = target.lstrip("/") if target.startswith("/") else _norm(f"{base_dir}/{target}")
        out[rel.get("Id", "")] = (full, rel.get("Type", ""))
    return out


def _norm(path: str) -> str:
    parts: list[str] = []
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
        else:
            parts.append(seg)
    return "/".join(parts)


def _core_props(zf: zipfile.ZipFile) -> dict:
    try:
        root = _xml(zf, "docProps/core.xml")
    except InvalidDocumentError:
        return {}
    def g(prefix, tag):
        el = root.find(_q(prefix, tag))
        return (el.text or "").strip() if el is not None else ""
    return {k: v for k, v in {"title": g("dc", "title"), "author": g("dc", "creator"),
                              "created": g("dcterms", "created")[:10], "modified": g("dcterms", "modified")[:10]}.items() if v}


# ------------------------------------------------------------------ xlsx
def col_letters(index: int) -> str:
    """1 → A, 27 → AA"""
    s = ""
    while index:
        index, rem = divmod(index - 1, 26)
        s = chr(65 + rem) + s
    return s


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref)
    n = 0
    for ch in (letters.group(0) if letters else "A"):
        n = n * 26 + ord(ch) - 64
    return n


def _range(first: str, last: str) -> str:
    return first if first == last else f"{first}:{last}"


_BUILTIN_DATE = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))


def _fmt_kind(code: str) -> str:
    c = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code)
    if "%" in c:
        return "percent"
    if re.search(r"[ymdhs]", c, re.I):
        return "date"
    return "num"


def _xlsx_styles(zf: zipfile.ZipFile) -> list[str]:
    """셀 서식 인덱스(s) → 'date'|'percent'|'num'."""
    try:
        root = _xml(zf, "xl/styles.xml")
    except InvalidDocumentError:
        return []
    custom = {int(n.get("numFmtId", -1)): n.get("formatCode", "") for n in root.findall("m:numFmts/m:numFmt", _NS)}
    kinds = []
    for xf in root.findall("m:cellXfs/m:xf", _NS):
        fid = int(xf.get("numFmtId", 0) or 0)
        if fid in custom:
            kinds.append(_fmt_kind(custom[fid]))
        elif fid in _BUILTIN_DATE:
            kinds.append("date")
        elif fid in (9, 10):
            kinds.append("percent")
        else:
            kinds.append("num")
    return kinds


def _fmt_number(raw: str, kind: str, epoch1904: bool) -> str:
    try:
        x = float(raw)
    except ValueError:
        return raw
    if kind == "date" and 0 < x < 2958466:
        base = date(1904, 1, 1) if epoch1904 else date(1899, 12, 30)
        d = base + timedelta(days=int(x))
        frac = x - int(x)
        if frac > 1e-9:
            secs = round(frac * 86400)
            return f"{d.isoformat()} {secs // 3600:02d}:{secs % 3600 // 60:02d}"
        return d.isoformat()
    if kind == "percent":
        return f"{round(x * 100, 4):g}%"
    return f"{x:.12g}" if ("." in raw or "e" in raw.lower()) else raw


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    out = []
    for si in _xml(zf, "xl/sharedStrings.xml").findall("m:si", _NS):
        parts = []
        for child in si:
            if child.tag == _q("m", "t"):
                parts.append(child.text or "")
            elif child.tag == _q("m", "r"):  # 서식 있는 텍스트. 후리가나(rPh)는 제외
                parts.append("".join(t.text or "" for t in child.findall("m:t", _NS)))
        out.append("".join(parts))
    return out


def _xlsx(data: bytes) -> Extracted:
    zf = _open_zip(data)
    try:
        wb = _xml(zf, "xl/workbook.xml")
        rels = _rels(zf, "xl", "xl/_rels/workbook.xml.rels")
        shared, styles = _shared_strings(zf), _xlsx_styles(zf)
        pr = wb.find("m:workbookPr", _NS)
        epoch1904 = pr is not None and pr.get("date1904") in ("1", "true")
        segments: list[Segment] = []
        warnings: list[str] = []
        hidden = 0
        for sheet in wb.findall("m:sheets/m:sheet", _NS):
            if sheet.get("state") in ("hidden", "veryHidden"):
                hidden += 1
                continue
            name = sheet.get("name", "Sheet")
            target = rels.get(sheet.get(_q("r", "id"), ""), ("", ""))[0]
            if not target or target not in zf.namelist():
                continue
            segs, trunc = _xlsx_sheet(_xml(zf, target), name, shared, styles, epoch1904)
            segments.extend(segs)
            if trunc:
                warnings.append(f"시트 '{name}' 은(는) {MAX_ROWS_PER_SHEET}행까지만 색인했습니다")
        if hidden:
            warnings.append(f"숨김 시트 {hidden}개는 색인하지 않았습니다")
        if not segments:
            raise InvalidDocumentError("텍스트가 있는 셀이 없습니다")
        return Extracted(segments, _core_props(zf), warnings)
    finally:
        zf.close()


def _xlsx_sheet(root: ET.Element, sheet: str, shared: list[str], styles: list[str], epoch1904: bool):
    rows: list[tuple[int, list[tuple[str, str]]]] = []
    truncated = False
    for ri, row in enumerate(root.findall("m:sheetData/m:row", _NS)):
        if ri >= MAX_ROWS_PER_SHEET:
            truncated = True
            break
        rnum = int(row.get("r", ri + 1))
        cells: list[tuple[str, str]] = []
        col = 0
        for c in row.findall("m:c", _NS)[:MAX_COLS]:
            col += 1
            ref = c.get("r") or f"{col_letters(col)}{rnum}"
            col = _col_index(ref)
            typ = c.get("t", "n")
            if typ == "inlineStr":
                val = "".join(t.text or "" for t in c.iter(_q("m", "t")))
            else:
                v = c.find("m:v", _NS)
                val = (v.text or "") if v is not None else ""
                if typ == "s":
                    val = shared[int(val)] if val.isdigit() and int(val) < len(shared) else ""
                elif typ == "b":
                    val = "TRUE" if val == "1" else "FALSE"
                elif typ == "e":
                    val = ""  # #DIV/0! 같은 오류 값은 색인하지 않는다
                elif typ in ("n", "") and val:
                    idx = int(c.get("s", 0) or 0)
                    val = _fmt_number(val, styles[idx] if idx < len(styles) else "num", epoch1904)
            if val.strip():
                cells.append((ref, val.strip()))
        if cells:
            rows.append((rnum, cells))
    if not rows:
        return [], truncated
    header: dict[int, str] = {}
    first_row, first_cells = rows[0]
    if len(first_cells) >= 2 and not any(re.fullmatch(r"-?[\d.,%]+", v) for _, v in first_cells):
        header = {_col_index(ref): v for ref, v in first_cells}
    segs: list[Segment] = []
    for rownum, cells in rows:
        loc = f"시트 '{sheet}' · 셀 {_range(cells[0][0], cells[-1][0])}"
        if header and rownum != first_row:
            text = " | ".join(f"{header.get(_col_index(ref), ref)}: {val}" for ref, val in cells)
        else:
            text = " | ".join(val for _, val in cells)
        segs.append((sheet, loc, text))
    return segs, truncated


def extract_xlsx(src) -> list[Segment]:
    return _xlsx(_bytes(src)).segments


# ------------------------------------------------------------------ pptx
_SKIP_PH = {"sldNum", "ftr", "dt", "hdr"}


def _runs_text(p: ET.Element) -> str:
    out = []
    for child in p:
        tag = child.tag
        if tag == _q("a", "r"):
            t = child.find("a:t", _NS)
            out.append(t.text or "" if t is not None else "")
        elif tag == _q("a", "br"):
            out.append("\n")
        elif tag == _q("a", "fld"):
            if not (child.get("type", "").lower().startswith(("slidenum", "datetime"))):
                t = child.find("a:t", _NS)
                out.append(t.text or "" if t is not None else "")
    return "".join(out).strip()


def _shape_texts(tree: ET.Element, title_box: list[str], paras: list[str]) -> None:
    for el in tree:
        tag = el.tag
        if tag == _q("p", "sp"):
            ph = el.find("p:nvSpPr/p:nvPr/p:ph", _NS)
            ptype = ph.get("type", "") if ph is not None else ""
            if ptype in _SKIP_PH:
                continue
            texts = [t for t in (_runs_text(p) for p in el.iter(_q("a", "p"))) if t]
            if ptype in ("title", "ctrTitle") and texts and not title_box:
                title_box.append(" ".join(texts))
            else:
                paras.extend(texts)
        elif tag == _q("p", "grpSp"):
            _shape_texts(el, title_box, paras)
        elif tag == _q("p", "graphicFrame"):
            for tbl in el.iter(_q("a", "tbl")):
                for tr in tbl.findall("a:tr", _NS):
                    cells = [" ".join(t for t in (_runs_text(p) for p in tc.iter(_q("a", "p"))) if t)
                             for tc in tr.findall("a:tc", _NS)]
                    if any(cells):
                        paras.append(" | ".join(cells))


def _slide_notes(zf: zipfile.ZipFile, rels: dict[str, tuple[str, str]]) -> str:
    for target, typ in rels.values():
        if typ.endswith("/notesSlide") and target in zf.namelist():
            root = _xml(zf, target)
            texts = []
            for sp in root.iter(_q("p", "sp")):
                ph = sp.find("p:nvSpPr/p:nvPr/p:ph", _NS)
                if ph is not None and ph.get("type") == "body":
                    texts += [t for t in (_runs_text(p) for p in sp.iter(_q("a", "p"))) if t]
            return " ".join(texts)
    return ""


def _diagram_text(zf: zipfile.ZipFile, rels: dict[str, tuple[str, str]]) -> list[str]:
    out = []
    for target, typ in rels.values():
        if typ.endswith("/diagramData") and target in zf.namelist():
            root = _xml(zf, target)
            for pt in root.iter("{http://schemas.openxmlformats.org/drawingml/2006/diagram}pt"):
                t = " ".join(x.text or "" for x in pt.iter(_q("a", "t"))).strip()
                if t:
                    out.append(t)
    return out


def _pptx(data: bytes) -> Extracted:
    zf = _open_zip(data)
    try:
        pres = _xml(zf, "ppt/presentation.xml")
        prels = _rels(zf, "ppt", "ppt/_rels/presentation.xml.rels")
        segments: list[Segment] = []
        for n, sld in enumerate(pres.findall("p:sldIdLst/p:sldId", _NS), start=1):
            target = prels.get(sld.get(_q("r", "id"), ""), ("", ""))[0]
            if not target or target not in zf.namelist():
                continue
            slide = _xml(zf, target)
            base, name = target.rsplit("/", 1)
            srels = _rels(zf, base, f"{base}/_rels/{name}.rels")
            title_box: list[str] = []
            paras: list[str] = []
            tree = slide.find("p:cSld/p:spTree", _NS)
            if tree is not None:
                _shape_texts(tree, title_box, paras)
            paras += _diagram_text(zf, srels)
            notes = _slide_notes(zf, srels)
            parts = title_box + paras + ([f"발표자 노트: {notes}"] if notes else [])
            if parts:
                hidden = slide.get("show") == "0"
                segments.append((title_box[0] if title_box else f"슬라이드 {n}",
                                 f"슬라이드 {n}" + (" (숨김)" if hidden else ""), "\n".join(parts)))
        if not segments:
            raise InvalidDocumentError("텍스트가 있는 슬라이드가 없습니다")
        return Extracted(segments, _core_props(zf))
    finally:
        zf.close()


def extract_pptx(src) -> list[Segment]:
    return _pptx(_bytes(src)).segments


# ------------------------------------------------------------------ docx
def _heading_styles(zf: zipfile.ZipFile) -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        root = _xml(zf, "word/styles.xml")
    except InvalidDocumentError:
        return out
    for st in root.findall("w:style", _NS):
        sid = st.get(_q("w", "styleId"), "")
        nm = st.find("w:name", _NS)
        name = (nm.get(_q("w", "val"), "") if nm is not None else "").lower()
        outline = st.find("w:pPr/w:outlineLvl", _NS)
        m = re.match(r"^(heading|제목)\s*(\d)", name)
        if m:
            out[sid] = int(m.group(2))
        elif name in ("title", "표제", "제목") or outline is not None:
            out[sid] = 1
    return out


def _par_text(p: ET.Element) -> str:
    out = []
    for el in p.iter():
        tag = el.tag
        if tag == _q("w", "t"):
            out.append(el.text or "")
        elif tag == _q("w", "tab"):
            out.append("\t")
        elif tag == _q("w", "br") and el.get(_q("w", "type")) != "page":
            out.append("\n")
        elif tag == _q("w", "noBreakHyphen"):
            out.append("-")
    return "".join(out).strip()


def _body_items(parent: ET.Element):
    for el in parent:
        if el.tag in (_q("w", "p"), _q("w", "tbl")):
            yield el
        elif el.tag == _q("w", "sdt"):  # 콘텐츠 컨트롤
            content = el.find("w:sdtContent", _NS)
            if content is not None:
                yield from _body_items(content)


def _docx(data: bytes) -> Extracted:
    zf = _open_zip(data)
    try:
        doc = _xml(zf, "word/document.xml")
        body = doc.find("w:body", _NS)
        if body is None:
            raise InvalidDocumentError("본문 구조 오류")
        styles = _heading_styles(zf)
        props = _core_props(zf)
        rendered = any(True for _ in doc.iter(_q("w", "lastRenderedPageBreak")))
        page = 1
        heading = props.get("title", "")
        segments: list[Segment] = []
        buf: list[tuple[int, int, str]] = []  # (문단 번호, 쪽, 텍스트)
        para_no = tbl_no = 0
        warnings: list[str] = []

        def flush() -> None:
            nonlocal buf
            if not buf:
                return
            a, b = buf[0][0], buf[-1][0]
            p1, p2 = buf[0][1], buf[-1][1]
            loc = f"문단 {a}" if a == b else f"문단 {a}–{b}"
            if rendered or p2 > 1:
                loc += f" · 약 {p1}쪽" if p1 == p2 else f" · 약 {p1}–{p2}쪽"
            segments.append((heading, loc, "\n".join(t for _, _, t in buf)))
            buf = []

        def count_breaks(el: ET.Element) -> int:
            if rendered:
                return sum(1 for _ in el.iter(_q("w", "lastRenderedPageBreak")))
            return sum(1 for b in el.iter(_q("w", "br")) if b.get(_q("w", "type")) == "page")

        for item in _body_items(body):
            if item.tag == _q("w", "p"):
                page += count_breaks(item)
                text = _par_text(item)
                if not text:
                    continue
                style = item.find("w:pPr/w:pStyle", _NS)
                sid = style.get(_q("w", "val"), "") if style is not None else ""
                if sid in styles or re.match(r"^(heading|제목)\s*\d", sid, re.I):
                    flush()
                    heading = text
                    continue
                para_no += 1
                buf.append((para_no, page, text))
                if sum(len(t) for _, _, t in buf) >= 700:
                    flush()
            else:  # 표
                flush()
                tbl_no += 1
                rows = []
                for tr in item.findall("w:tr", _NS):
                    cells = [" ".join(t for t in (_par_text(p) for p in tc.iter(_q("w", "p"))) if t)
                             for tc in tr.findall("w:tc", _NS)]
                    rows.append(cells)
                page_here = page
                page += count_breaks(item)
                header: list[str] = []
                if rows and len([c for c in rows[0] if c]) >= 2 and not any(re.fullmatch(r"-?[\d.,%]+", c) for c in rows[0] if c):
                    header = rows[0]
                for ri, cells in enumerate(rows, start=1):
                    if not any(cells):
                        continue
                    if header and ri > 1:
                        text = " | ".join(f"{header[i] if i < len(header) and header[i] else i + 1}: {c}"
                                          for i, c in enumerate(cells) if c)
                    else:
                        text = " | ".join(c for c in cells if c)
                    loc = f"표 {tbl_no} · 행 {ri}" + (f" · 약 {page_here}쪽" if rendered else "")
                    segments.append((heading, loc, text))
        flush()
        if "word/footnotes.xml" in zf.namelist():
            try:
                for fn in _xml(zf, "word/footnotes.xml").findall("w:footnote", _NS):
                    if fn.get(_q("w", "type")) in ("separator", "continuationSeparator"):
                        continue
                    t = " ".join(x for x in (_par_text(p) for p in fn.iter(_q("w", "p"))) if x)
                    if t:
                        segments.append(("각주", f"각주 {fn.get(_q('w', 'id'), '')}", t))
            except InvalidDocumentError:
                warnings.append("각주를 읽지 못했습니다")
        if not segments:
            raise InvalidDocumentError("텍스트가 없는 문서입니다")
        return Extracted(segments, props, warnings)
    finally:
        zf.close()


def extract_docx(src) -> list[Segment]:
    return _docx(_bytes(src)).segments


# ------------------------------------------------------------------ csv
def _csv(data: bytes) -> Extracted:
    if not data.strip():
        raise InvalidDocumentError("빈 파일입니다")
    text, enc = decode_text(data)
    warnings = []
    if enc == "utf-8(replace)":
        warnings.append("인코딩을 판별하지 못해 일부 문자가 손상되었을 수 있습니다")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ","
    rows: list[list[str]] = []
    truncated = False
    try:
        for i, row in enumerate(csv.reader(io.StringIO(text), delimiter=delim)):
            if i >= MAX_CSV_ROWS:
                truncated = True
                break
            if any(c.strip() for c in row):
                rows.append((i + 1, [c.strip() for c in row[:MAX_COLS]]))
    except csv.Error:
        raise InvalidDocumentError("CSV 형식 오류") from None
    if not rows:
        raise InvalidDocumentError("텍스트가 있는 행이 없습니다")
    first = rows[0][1]
    header = first if len([c for c in first if c]) >= 2 and not any(re.fullmatch(r"-?[\d.,%]+", c) for c in first if c) else []
    group = 1 if len(rows) <= 2000 else 10
    segs: list[Segment] = []
    for k in range(0, len(rows), group):
        part = rows[k:k + group]
        lines = []
        for rn, cells in part:
            if header and rn != rows[0][0]:
                lines.append(" | ".join(f"{header[i] if i < len(header) and header[i] else i + 1}: {c}"
                                        for i, c in enumerate(cells) if c))
            else:
                lines.append(" | ".join(c for c in cells if c))
        a, b = part[0][0], part[-1][0]
        segs.append(("CSV", f"행 {a}" if a == b else f"행 {a}–{b}", "\n".join(lines)))
    if truncated:
        warnings.append(f"{MAX_CSV_ROWS}행까지만 색인했습니다")
    return Extracted(segs, {}, warnings)


def extract_csv(src) -> list[Segment]:
    return _csv(_bytes(src)).segments


# ------------------------------------------------------------------ pdf
_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj\b(.*?)endobj", re.S)
_REF_RE = re.compile(rb"(\d+)\s+\d+\s+R")
_WIDE_ENC = re.compile(rb"/Encoding\s*/(Uni\w+-(?:UCS2|UTF16)-[HV]|Identity-[HV])")
_NAME_RE = r"[A-Za-z0-9_.+#-]+"
_ESC = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}


def _a85(data: bytes) -> bytes:
    import base64
    d = data.strip()
    if d.startswith(b"<~"):
        d = d[2:]
    return base64.a85decode(d, adobe=False) if not d.endswith(b"~>") else base64.a85decode(d[:-2])


def _decode_stream(dict_part: bytes, raw: bytes) -> bytes | None:
    m = re.search(rb"/Filter\s*(\[[^\]]*\]|/\w+)", dict_part)
    filters = re.findall(rb"/(\w+)", m.group(1)) if m else []
    data = raw
    for f in filters:
        try:
            if f in (b"FlateDecode", b"Fl"):
                data = zlib.decompressobj().decompress(data)  # 뒤따르는 잔여 바이트 허용
            elif f in (b"ASCIIHexDecode", b"AHx"):
                data = bytes.fromhex(re.sub(rb"\s+|>", b"", data).decode())
            elif f in (b"ASCII85Decode", b"A85"):
                data = _a85(data)
            else:
                return None  # 지원하지 않는 필터(LZW, DCT 등)
        except (zlib.error, ValueError):
            return None
    return data


class _Pdf:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.objs: dict[int, bytes] = {int(m.group(1)): m.group(3) for m in _OBJ_RE.finditer(raw)}
        self._expand_object_streams()

    def _split(self, body: bytes) -> tuple[bytes, bytes | None]:
        """객체 본문을 (사전 부분, 스트림 원본 바이트) 로 나눈다. 스트림이 없으면 (본문, None)."""
        m = re.search(rb"\bstream\r?\n", body)
        if not m:
            return body, None
        d, start = body[:m.start()], m.end()
        ln = re.search(rb"/Length\s+(\d+)(?!\s+\d+\s+R)", d)  # 직접 지정된 길이를 우선 사용
        if ln and start + int(ln.group(1)) <= len(body):
            return d, body[start:start + int(ln.group(1))]
        end = body.rfind(b"endstream")
        if end < 0:
            return d, None
        data = body[start:end]
        if data.endswith(b"\r\n"):
            data = data[:-2]
        elif data.endswith(b"\n"):
            data = data[:-1]
        return d, data

    def stream(self, no: int) -> bytes | None:
        body = self.objs.get(no)
        if body is None:
            return None
        d, raw = self._split(body)
        return None if raw is None else _decode_stream(d, raw)

    def _expand_object_streams(self) -> None:
        for no, body in list(self.objs.items()):
            d, raw = self._split(body)
            if raw is None or not re.search(rb"/Type\s*/ObjStm", d):
                continue
            data = _decode_stream(d, raw)
            n = re.search(rb"/N\s+(\d+)", d)
            first = re.search(rb"/First\s+(\d+)", d)
            if data is None or not n or not first:
                continue
            head = data[:int(first.group(1))].split()
            pairs = [(int(head[i]), int(head[i + 1])) for i in range(0, min(len(head), int(n.group(1)) * 2) - 1, 2)
                     if head[i].isdigit() and head[i + 1].isdigit()]
            base = int(first.group(1))
            for k, (onum, off) in enumerate(pairs):
                end = pairs[k + 1][1] if k + 1 < len(pairs) else len(data) - base
                self.objs.setdefault(onum, data[base + off: base + end])

    # -- 사전 값 추출 -------------------------------------------------------
    @staticmethod
    def _balanced(body: bytes, start: int) -> bytes:
        """body[start:] 가 `<<` 로 시작할 때 짝이 맞는 `<< ... >>` 를 반환."""
        depth, i = 0, start
        while i < len(body) - 1:
            two = body[i:i + 2]
            if two == b"<<":
                depth += 1
                i += 2
            elif two == b">>":
                depth -= 1
                i += 2
                if depth == 0:
                    return body[start:i]
            else:
                i += 1
        return body[start:]

    def value_dict(self, body: bytes, key: bytes) -> bytes:
        """`/Key << ... >>` 또는 `/Key N 0 R` 의 사전 본문."""
        m = re.search(rb"/" + key + rb"\s*(<<|(\d+)\s+\d+\s+R)", body)
        if not m:
            return b""
        if m.group(1) == b"<<":
            return self._balanced(body, m.start(1))
        return self.objs.get(int(m.group(2)), b"")

    def pages(self) -> list[tuple[bytes, bytes]]:
        """[(페이지 사전, 상속된 Resources 사전)] — 페이지 트리 순서."""
        root = next((n for n, b in self.objs.items() if re.search(rb"/Type\s*/Catalog", b)), None)
        out: list[tuple[bytes, bytes]] = []
        seen: set[int] = set()

        def walk(no: int, inherited: bytes) -> None:
            if no in seen or no not in self.objs or len(out) >= MAX_PDF_PAGES:
                return
            seen.add(no)
            body = self.objs[no]
            res = self.value_dict(body, b"Resources") or inherited
            if re.search(rb"/Type\s*/Pages\b", body):
                m = re.search(rb"/Kids\s*\[(.*?)\]", body, re.S)
                for k in (_REF_RE.findall(m.group(1)) if m else []):
                    walk(int(k), res)
            elif re.search(rb"/Type\s*/Page\b", body):
                out.append((body, res))

        if root is not None:
            m = re.search(rb"/Pages\s+(\d+)\s+\d+\s+R", self.objs[root])
            if m:
                walk(int(m.group(1)), b"")
        if not out:
            for n in sorted(self.objs):
                if re.search(rb"/Type\s*/Page\b", self.objs[n]):
                    out.append((self.objs[n], self.value_dict(self.objs[n], b"Resources")))
        return out


class _Font:
    def __init__(self, pdf: _Pdf, body: bytes):
        self.map: dict[int, str] = {}
        self.width = 1
        self.mode = "latin"  # latin | map | wide | cid
        d = body
        is_type0 = bool(re.search(rb"/Subtype\s*/Type0", d))
        tu = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", d)
        if tu:
            cm = pdf.stream(int(tu.group(1)))
            if cm:
                self._parse_cmap(cm)
        if self.map:
            self.mode = "map"
        elif is_type0 and _WIDE_ENC.search(d):
            enc = _WIDE_ENC.search(d).group(1)
            if enc.startswith(b"Identity"):
                self.mode = "cid"  # ToUnicode 없는 CID 글꼴 — 글자 복원 불가
            else:
                self.mode, self.width = "wide", 2
        elif is_type0:
            self.mode = "cid"

    def _parse_cmap(self, cm: bytes) -> None:
        for blk in re.findall(rb"begincodespacerange(.*?)endcodespacerange", cm, re.S):
            m = re.search(rb"<([0-9A-Fa-f]+)>", blk)
            if m:
                self.width = max(1, len(m.group(1)) // 2)
        def u(h: bytes) -> str:
            return bytes.fromhex(h.decode()).decode("utf-16-be", errors="ignore")
        for blk in re.findall(rb"beginbfchar(.*?)endbfchar", cm, re.S):
            for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", blk):
                self.map[int(src, 16)] = u(dst) if dst else ""
        for blk in re.findall(rb"beginbfrange(.*?)endbfrange", cm, re.S):
            for m in re.finditer(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f]*>)", blk):
                lo, hi = int(m.group(1), 16), int(m.group(2), 16)
                tgt = m.group(3)
                if tgt.startswith(b"["):
                    for i, d in enumerate(re.findall(rb"<([0-9A-Fa-f]*)>", tgt)):
                        if lo + i <= hi:
                            self.map[lo + i] = u(d)
                else:
                    base = u(tgt[1:-1])
                    if base and hi - lo < 65536:
                        for i in range(hi - lo + 1):
                            self.map[lo + i] = base[:-1] + chr(ord(base[-1]) + i)

    def decode(self, data: bytes) -> tuple[str, int]:
        """(텍스트, 복원 실패 글자 수)"""
        if self.mode == "cid":
            return "", len(data) // 2
        if data[:2] in (b"\xfe\xff", b"\xff\xfe"):
            return data.decode("utf-16", errors="ignore"), 0
        if self.mode == "wide":
            return data.decode("utf-16-be", errors="ignore"), 0
        if self.mode == "map":
            out, miss, w = [], 0, self.width
            for i in range(0, len(data) - w + 1, w):
                code = int.from_bytes(data[i:i + w], "big")
                ch = self.map.get(code)
                if ch is None:
                    miss += 1
                else:
                    out.append(ch)
            return "".join(out), miss
        return data.decode("cp1252", errors="replace"), 0


_TOK = re.compile(rb"[\x00\t\n\x0c\r ]*(?:(?P<com>%[^\r\n]*)|(?P<dict><<|>>)|(?P<hex><[0-9A-Fa-f\s]*>)|(?P<arr>[\[\]])"
                  rb"|(?P<name>/[^\s\[\]()<>/%]*)|(?P<num>[+-]?(?:\d+\.?\d*|\.\d+))|(?P<op>[A-Za-z'\"*][A-Za-z0-9'\"*]*))")


def _read_literal(data: bytes, i: int) -> tuple[bytes, int]:
    depth, out, n = 1, bytearray(), len(data)
    i += 1
    while i < n and depth:
        c = data[i]
        if c == 0x5C and i + 1 < n:
            nxt = data[i + 1]
            if 0x30 <= nxt <= 0x37:
                j = i + 1
                while j < n and j < i + 4 and 0x30 <= data[j] <= 0x37:
                    j += 1
                out.append(int(data[i + 1:j], 8) & 0xFF)
                i = j
                continue
            if nxt in _ESC:
                out.append(_ESC[nxt])
            elif nxt not in (10, 13):
                out.append(nxt)
            i += 2
            continue
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                i += 1
                break
        out.append(c)
        i += 1
    return bytes(out), i


def _content_ops(data: bytes):
    """콘텐츠 스트림을 (연산자, 피연산자 목록) 으로 순회. 문자열은 bytes, 배열은 list."""
    i, n, stack, arr = 0, len(data), [], None
    while i < n:
        j = i
        while j < n and data[j] in b"\x00\t\n\x0c\r ":
            j += 1
        if j >= n:
            break
        if data[j] == 0x28:  # (
            s, i = _read_literal(data, j)
            (arr if arr is not None else stack).append(s)
            continue
        m = _TOK.match(data, i)
        if not m:
            i = j + 1
            continue
        i = m.end()
        kind = m.lastgroup
        tok = m.group(kind)
        if kind == "hex":
            h = re.sub(rb"\s+", b"", tok[1:-1])
            (arr if arr is not None else stack).append(bytes.fromhex((h + b"0" * (len(h) % 2)).decode()))
        elif kind == "arr":
            if tok == b"[":
                arr = []
            elif arr is not None:
                stack.append(arr)
                arr = None
        elif kind == "name":
            (arr if arr is not None else stack).append(("name", tok[1:].decode("latin-1")))
        elif kind == "num":
            (arr if arr is not None else stack).append(float(tok))
        elif kind == "op":
            op = tok.decode("latin-1")
            if op == "BI":  # 인라인 이미지는 건너뜀
                end = data.find(b"EI", i)
                i = n if end < 0 else end + 2
                stack = []
                continue
            yield op, stack
            stack = []


def _page_text(pdf: _Pdf, page: bytes, resources: bytes, fonts_cache: dict[int, _Font]) -> tuple[str, int]:
    fdict = pdf.value_dict(resources, b"Font")
    font_refs = {m.group(1).decode(): int(m.group(2)) for m in re.finditer(rb"/(" + _NAME_RE.encode() + rb")\s+(\d+)\s+\d+\s+R", fdict)}
    cm = re.search(rb"/Contents\s*(\[(.*?)\]|(\d+)\s+\d+\s+R)", page, re.S)
    refs = [int(x) for x in _REF_RE.findall(cm.group(0))] if cm else []
    content = b"\n".join(pdf.stream(r) or b"" for r in refs)
    font: _Font | None = None
    lines: list[str] = []
    cur: list[str] = []
    y = None
    miss = 0

    def newline() -> None:
        nonlocal cur
        if cur:
            lines.append("".join(cur).strip())
            cur = []

    def show(b: bytes) -> None:
        nonlocal miss
        if font is None:
            return
        t, m = font.decode(b)
        miss += m
        cur.append(t)

    for op, args in _content_ops(content):
        nums = [a for a in args if isinstance(a, float)]
        if op == "Tf":
            nm = next((a[1] for a in args if isinstance(a, tuple)), None)
            ref = font_refs.get(nm) if nm else None
            if ref is not None:
                if ref not in fonts_cache:
                    fonts_cache[ref] = _Font(pdf, pdf.objs.get(ref, b""))
                font = fonts_cache[ref]
            else:
                font = None
        elif op == "BT":
            newline()
            y = None
        elif op in ("Td", "TD") and len(nums) >= 2:
            if abs(nums[1]) > 0.01:
                newline()
            elif nums[0] > 0 and cur:
                cur.append(" ")
        elif op == "Tm" and len(nums) >= 6:
            if y is not None and abs(nums[5] - y) > 0.5:
                newline()
            elif cur:
                cur.append(" ")
            y = nums[5]
        elif op == "T*":
            newline()
        elif op in ("'", '"'):
            newline()
            for a in args:
                if isinstance(a, bytes):
                    show(a)
        elif op == "Tj":
            for a in args:
                if isinstance(a, bytes):
                    show(a)
        elif op == "TJ":
            for a in args:
                if isinstance(a, list):
                    for it in a:
                        if isinstance(it, bytes):
                            show(it)
                        elif isinstance(it, float) and it < -250 and cur:
                            cur.append(" ")
    newline()
    return "\n".join(l for l in lines if l), miss


def _pdf(raw: bytes) -> Extracted:
    if not raw.startswith(b"%PDF-"):
        raise InvalidDocumentError("PDF 형식이 아닙니다")
    if re.search(rb"/Encrypt\s*(\d+\s+\d+\s+R|<<)", raw):
        raise InvalidDocumentError("암호화된 PDF는 지원하지 않습니다")
    pdf = _Pdf(raw)
    fonts: dict[int, _Font] = {}
    segments: list[Segment] = []
    warnings: list[str] = []
    missed_pages = 0
    for no, (page, res) in enumerate(pdf.pages(), start=1):
        text, miss = _page_text(pdf, page, res, fonts)
        if text.strip():
            segments.append((text.splitlines()[0][:60], f"p.{no}", text))
        elif miss:
            missed_pages += 1
    if missed_pages:
        warnings.append(f"{missed_pages}쪽은 글꼴 정보 부족으로 텍스트를 복원하지 못했습니다")
    if not segments:
        raise InvalidDocumentError("텍스트를 추출할 수 없습니다 (스캔본이거나 지원하지 않는 PDF 인코딩)")
    title = re.search(rb"/Title\s*\(([^)]{1,200})\)", raw)
    props = {"title": title.group(1).decode("latin-1").strip()} if title and title.group(1).isascii() else {}
    return Extracted(segments, props, warnings)


def extract_pdf(src) -> list[Segment]:
    return _pdf(_bytes(src)).segments


# ------------------------------------------------------------------ 통합 진입점
EXTRACTORS = {"xlsx": extract_xlsx, "pptx": extract_pptx, "pdf": extract_pdf, "docx": extract_docx, "csv": extract_csv}
_FULL = {"xlsx": _xlsx, "pptx": _pptx, "pdf": _pdf, "docx": _docx, "csv": _csv}
EXTRACTABLE = set(_FULL)  # 본문 추출 지원 형식 (md/txt 는 커넥터가 직접 처리)


def extract(ext: str, data: bytes) -> Extracted:
    ext = ext.lower().lstrip(".")
    if ext == "xlsm":
        ext = "xlsx"
    if ext not in _FULL:
        raise InvalidDocumentError("본문 추출을 지원하지 않는 형식입니다")
    return _FULL[ext](data)
