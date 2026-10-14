"""파일 형식별 본문 추출 (표준 라이브러리만 사용).

각 추출기는 ``list[Segment]`` = (소제목, 위치 표기, 텍스트) 를 반환한다. 위치 표기는 검색 결과/미리보기에 그대로 표시된다.

  - xlsx : "시트 '요약' · 셀 A5:D5"   (행 단위, 첫 행이 머리글이면 '머리글: 값' 형태로 텍스트화)
  - pptx : "슬라이드 3"              (제목·본문·표·발표자 노트)
  - pdf  : "p.2"                    (페이지)
  - md/txt : 공유폴더 Connector 가 "줄 12–18" 로 직접 계산

오류 처리: 손상/암호화/지원하지 않는 파일은 ``InvalidDocumentError`` 를 올린다(메시지에 본문 미포함).
압축 폭탄 방지를 위해 OOXML(zip) 은 항목 수·해제 크기를 제한한다.

!! PDF 한계 !! 이 추출기는 단순 텍스트 PDF(비압축 또는 Flate 압축, 문자열 직접 인코딩)만 지원한다.
스캔 PDF(OCR 필요), 임베디드 한글 폰트의 ToUnicode CMap 기반 PDF 등은 텍스트를 얻지 못할 수 있으며, 이 경우
"텍스트를 추출할 수 없습니다" 오류로 보고한다. 운영 단계에서는 검증된 PDF 추출 라이브러리/전용 추출 서버로 교체한다.
"""
from __future__ import annotations

import re
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET

from core.models import InvalidDocumentError, Segment

MAX_ZIP_MEMBERS = 2000
MAX_UNCOMPRESSED = 40 * 1024 * 1024
MAX_ROWS_PER_SHEET = 5000
MAX_PDF_PAGES = 500

_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


# ------------------------------------------------------------------ zip 공통
def _open_zip(path: Path) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(path)
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
        if b"<!DOCTYPE" in data or b"<!ENTITY" in data:  # XML 엔티티 확장 공격 차단
            raise InvalidDocumentError("허용되지 않는 XML 구조(DTD/ENTITY)")
        return ET.fromstring(data)
    except KeyError:
        raise InvalidDocumentError(f"필수 구성요소 누락: {name}") from None
    except ET.ParseError:
        raise InvalidDocumentError("XML 구조 오류") from None


def _rels(zf: zipfile.ZipFile, base_dir: str, rels_name: str) -> dict[str, str]:
    """relationship Id → 파일 경로(zip 내 정규화)."""
    out: dict[str, str] = {}
    try:
        root = _xml(zf, rels_name)
    except InvalidDocumentError:
        return out
    for rel in root.findall("rel:Relationship", _NS):
        target = rel.get("Target", "")
        full = target.lstrip("/") if target.startswith("/") else _norm(f"{base_dir}/{target}")
        out[rel.get("Id", "")] = full
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


def _row_range(first: str, last: str) -> str:
    return first if first == last else f"{first}:{last}"


def extract_xlsx(path: Path) -> list[Segment]:
    zf = _open_zip(path)
    try:
        wb = _xml(zf, "xl/workbook.xml")
        rels = _rels(zf, "xl", "xl/_rels/workbook.xml.rels")
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            for si in _xml(zf, "xl/sharedStrings.xml").findall("m:si", _NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
        segments: list[Segment] = []
        for sheet in wb.findall("m:sheets/m:sheet", _NS):
            name = sheet.get("name", "Sheet")
            target = rels.get(sheet.get(f"{{{_NS['r']}}}id", ""))
            if not target or target not in zf.namelist():
                continue
            segments.extend(_xlsx_sheet(_xml(zf, target), name, shared))
        if not segments:
            raise InvalidDocumentError("텍스트가 있는 셀이 없습니다")
        return segments
    finally:
        zf.close()


def _xlsx_sheet(root: ET.Element, sheet: str, shared: list[str]) -> list[Segment]:
    rows: list[tuple[int, list[tuple[str, str]]]] = []  # (행번호, [(셀주소, 값)])
    for row in root.findall("m:sheetData/m:row", _NS)[:MAX_ROWS_PER_SHEET]:
        cells: list[tuple[str, str]] = []
        for c in row.findall("m:c", _NS):
            ref, typ = c.get("r", ""), c.get("t", "n")
            if typ == "inlineStr":
                val = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
            else:
                v = c.find("m:v", _NS)
                val = (v.text or "") if v is not None else ""
                if typ == "s" and val.isdigit() and int(val) < len(shared):
                    val = shared[int(val)]
                elif typ == "b":
                    val = "TRUE" if val == "1" else "FALSE"
            if val.strip() and ref:
                cells.append((ref, val.strip()))
        if cells:
            rows.append((int(re.sub(r"\D", "", cells[0][0]) or 0), cells))
    if not rows:
        return []
    header: dict[int, str] = {}
    first_row, first_cells = rows[0]
    if len(first_cells) >= 2 and not any(re.fullmatch(r"-?[\d.,%]+", v) for _, v in first_cells):
        header = {_col_index(ref): v for ref, v in first_cells}  # 머리글 행
    segs: list[Segment] = []
    for rownum, cells in rows:
        rng = _row_range(cells[0][0], cells[-1][0])
        loc = f"시트 '{sheet}' · 셀 {rng}"
        if header and rownum != first_row:
            text = " | ".join(f"{header.get(_col_index(ref), ref)}: {val}" for ref, val in cells)
        else:
            text = " | ".join(val for _, val in cells)
        segs.append((sheet, loc, text))
    return segs


# ------------------------------------------------------------------ pptx
def extract_pptx(path: Path) -> list[Segment]:
    zf = _open_zip(path)
    try:
        pres = _xml(zf, "ppt/presentation.xml")
        rels = _rels(zf, "ppt", "ppt/_rels/presentation.xml.rels")
        segments: list[Segment] = []
        for n, sld in enumerate(pres.findall("p:sldIdLst/p:sldId", _NS), start=1):
            target = rels.get(sld.get(f"{{{_NS['r']}}}id", ""))
            if not target or target not in zf.namelist():
                continue
            slide = _xml(zf, target)
            title, paragraphs = _slide_text(slide)
            notes = _slide_notes(zf, target)
            parts = ([title] if title else []) + paragraphs
            if notes:
                parts.append("발표자 노트: " + notes)
            if parts:
                segments.append((title or f"슬라이드 {n}", f"슬라이드 {n}", "\n".join(parts)))
        if not segments:
            raise InvalidDocumentError("텍스트가 있는 슬라이드가 없습니다")
        return segments
    finally:
        zf.close()


def _para_text(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.iter(f"{{{_NS['a']}}}t")).strip()


def _slide_text(slide: ET.Element) -> tuple[str, list[str]]:
    title, paras = "", []
    for sp in slide.iter(f"{{{_NS['p']}}}sp"):
        ph = sp.find("p:nvSpPr/p:nvPr/p:ph", _NS)
        texts = [t for t in (_para_text(p) for p in sp.iter(f"{{{_NS['a']}}}p")) if t]
        if ph is not None and ph.get("type") in ("title", "ctrTitle") and texts and not title:
            title = " ".join(texts)
        else:
            paras.extend(texts)
    for tbl in slide.iter(f"{{{_NS['a']}}}tbl"):  # 표: 행 단위로 이어 붙임
        for tr in tbl.findall("a:tr", _NS):
            cells = [_para_text(tc) for tc in tr.findall("a:tc", _NS)]
            if any(cells):
                paras.append(" | ".join(cells))
    return title, paras


def _slide_notes(zf: zipfile.ZipFile, slide_path: str) -> str:
    base, name = slide_path.rsplit("/", 1)
    rels = _rels(zf, base, f"{base}/_rels/{name}.rels")
    for target in rels.values():
        if "notesSlides/" in target and target in zf.namelist():
            root = _xml(zf, target)
            texts = []
            for sp in root.iter(f"{{{_NS['p']}}}sp"):
                ph = sp.find("p:nvSpPr/p:nvPr/p:ph", _NS)
                if ph is not None and ph.get("type") == "body":
                    texts += [t for t in (_para_text(p) for p in sp.iter(f"{{{_NS['a']}}}p")) if t]
            return " ".join(texts)
    return ""


# ------------------------------------------------------------------ pdf (단순 텍스트 PDF)
_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj(.*?)endobj", re.S)
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_TOKEN_RE = re.compile(
    rb"/(?P<font>[A-Za-z0-9_.+-]+)\s+[\d.]+\s+Tf"
    rb"|<(?P<hex>[0-9A-Fa-f\s]*)>\s*Tj"
    rb"|\((?P<lit>(?:\\.|[^\\()])*)\)\s*Tj"
    rb"|\[(?P<arr>.*?)\]\s*TJ", re.S)
_ARR_ITEM = re.compile(rb"<([0-9A-Fa-f\s]*)>|\(((?:\\.|[^\\()])*)\)", re.S)
_WIDE_ENC = re.compile(rb"/Encoding\s*/(Uni\w+-(?:UCS2|UTF16)-[HV]|Identity-[HV])")
_ESC = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}


def _unescape(raw: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch != 0x5C or i + 1 >= len(raw):
            out.append(ch)
            i += 1
            continue
        nxt = raw[i + 1]
        if 0x30 <= nxt <= 0x37:  # \ddd 8진수 (최대 3자리)
            j = i + 1
            while j < len(raw) and j < i + 4 and 0x30 <= raw[j] <= 0x37:
                j += 1
            out.append(int(raw[i + 1:j], 8) & 0xFF)
            i = j
        elif nxt in _ESC:
            out.append(_ESC[nxt])
            i += 2
        elif nxt in (10, 13):  # 줄 이음
            i += 2
        else:
            out.append(nxt)
            i += 2
    return bytes(out)


def _decode(data: bytes, wide: bool) -> str:
    if data[:2] in (b"\xfe\xff", b"\xff\xfe"):
        return data.decode("utf-16", errors="ignore")
    if wide and len(data) % 2 == 0:
        return data.decode("utf-16-be", errors="ignore")
    return data.decode("latin-1")


def _hex_bytes(raw: bytes) -> bytes:
    h = re.sub(rb"\s+", b"", raw)
    return bytes.fromhex((h + b"0" * (len(h) % 2)).decode())


def _page_text(content: bytes, wide_fonts: set[bytes]) -> str:
    out: list[str] = []
    wide = False
    for m in _TOKEN_RE.finditer(content):
        if m.group("font") is not None:
            wide = m.group("font") in wide_fonts
        elif m.group("hex") is not None:
            out.append(_decode(_hex_bytes(m.group("hex")), wide))
        elif m.group("lit") is not None:
            out.append(_decode(_unescape(m.group("lit")), wide))
        else:
            parts = []
            for item in _ARR_ITEM.finditer(m.group("arr")):
                if item.group(1) is not None:
                    parts.append(_decode(_hex_bytes(item.group(1)), wide))
                else:
                    parts.append(_decode(_unescape(item.group(2) or b""), wide))
            out.append("".join(parts))
    return "\n".join(t for t in out if t.strip())


def _wide_font_names(objs: dict[int, bytes]) -> set[bytes]:
    """2바이트 코드(Unicode CMap/Identity) 인코딩을 쓰는 Type0 폰트의 리소스 이름 집합."""
    wide_ids = {n for n, b in objs.items() if re.search(rb"/Subtype\s*/Type0", b) and _WIDE_ENC.search(b)}
    names: set[bytes] = set()
    for n in wide_ids:
        m = re.search(rb"/Name\s*/([A-Za-z0-9_.+-]+)", objs[n])
        if m:
            names.add(m.group(1))
    for body in objs.values():  # 리소스: /F2 12 0 R
        for name, num in re.findall(rb"/([A-Za-z0-9_.+-]+)\s+(\d+)\s+0\s+R", body):
            if int(num) in wide_ids:
                names.add(name)
    return names


def extract_pdf(path: Path) -> list[Segment]:
    try:
        raw = path.read_bytes()
    except OSError:
        raise InvalidDocumentError("파일을 읽을 수 없습니다") from None
    if not raw.startswith(b"%PDF-"):
        raise InvalidDocumentError("PDF 형식이 아닙니다")
    if b"/Encrypt" in raw:
        raise InvalidDocumentError("암호화된 PDF는 지원하지 않습니다")
    objs: dict[int, bytes] = {int(m.group(1)): m.group(3) for m in _OBJ_RE.finditer(raw)}
    # 페이지 순서: /Type /Pages 의 /Kids 순서. 없으면 객체 번호 순
    kids: list[int] = []
    for body in objs.values():
        if re.search(rb"/Type\s*/Pages\b", body):
            m = re.search(rb"/Kids\s*\[(.*?)\]", body, re.S)
            if m:
                kids = [int(x) for x in re.findall(rb"(\d+)\s+0\s+R", m.group(1))]
                break
    pages = [k for k in kids if k in objs and re.search(rb"/Type\s*/Page\b", objs[k])] or sorted(
        n for n, b in objs.items() if re.search(rb"/Type\s*/Page\b", b))
    wide_fonts = _wide_font_names(objs)
    segments: list[Segment] = []
    for no, obj_no in enumerate(pages[:MAX_PDF_PAGES], start=1):
        contents = re.search(rb"/Contents\s*(\[(.*?)\]|(\d+)\s+0\s+R)", objs[obj_no], re.S)
        refs = [int(x) for x in re.findall(rb"(\d+)\s+0\s+R", contents.group(0))] if contents else []
        text_parts = []
        for ref in refs:
            body = objs.get(ref, b"")
            sm = _STREAM_RE.search(body)
            if not sm:
                continue
            data = sm.group(1)
            if re.search(rb"/FlateDecode", body[: sm.start()]):
                try:
                    data = zlib.decompress(data)
                except zlib.error:
                    continue
            text_parts.append(_page_text(data, wide_fonts))
        text = "\n".join(t for t in text_parts if t).strip()
        if text:
            first_line = text.splitlines()[0][:60]
            segments.append((first_line, f"p.{no}", text))
    if not segments:
        raise InvalidDocumentError("텍스트를 추출할 수 없습니다 (스캔본이거나 지원하지 않는 PDF 인코딩)")
    return segments


EXTRACTORS = {"xlsx": extract_xlsx, "pptx": extract_pptx, "pdf": extract_pdf}
