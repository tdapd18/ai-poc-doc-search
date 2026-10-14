"""테스트 보조: 표준 라이브러리만으로 최소 xlsx / pdf 파일을 만든다 (샘플 생성기와 별개의 독립 경로)."""
from __future__ import annotations

import json
import zipfile
import zlib
from pathlib import Path
from xml.sax.saxutils import escape


def col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def make_xlsx(path: Path, sheets: dict[str, list[list]], shared: bool = True) -> None:
    """sheets = {시트명: [[셀,...],...]}  (숫자는 숫자 셀, 문자열은 sharedStrings 또는 inlineStr)"""
    strings: list[str] = []
    sheet_xml = []
    for rows in sheets.values():
        out = []
        for r, row in enumerate(rows, start=1):
            cells = []
            for c, v in enumerate(row, start=1):
                ref = f"{col(c)}{r}"
                if isinstance(v, (int, float)):
                    cells.append(f'<c r="{ref}"><v>{v}</v></c>')
                elif shared:
                    strings.append(str(v))
                    cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
                else:
                    cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>')
            out.append(f'<row r="{r}">{"".join(cells)}</row>')
        sheet_xml.append('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                         + "".join(out) + "</sheetData></worksheet>")
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' \
         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    wb = f"<workbook {ns}><sheets>" + "".join(
        f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(sheets, 1)) + "</sheets></workbook>"
    rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
        f'<Relationship Id="rId{i}" Type="x" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1)
    ) + "</Relationships>"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        for i, x in enumerate(sheet_xml, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", x)
        if shared:
            z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                       + "".join(f"<si><t>{escape(s)}</t></si>" for s in strings) + "</sst>")


def make_pdf(path: Path, pages: list[str], flate: bool = False, wide: bool = False) -> None:
    """텍스트 PDF. wide=True 면 2바이트 코드(UniKS-UCS2-H) 16진 문자열, 아니면 Helvetica 리터럴 문자열."""
    objs: list[bytes] = []
    n = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    for i, text in enumerate(pages):
        page_no, content_no = 3 + 2 * i, 4 + 2 * i
        if wide:
            data = f"BT /F1 12 Tf 50 750 Td <{text.encode('utf-16-be').hex()}> Tj ET".encode()
        else:
            data = ("BT /F1 12 Tf 50 750 Td (" + text.replace("(", r"\(").replace(")", r"\)") + ") Tj ET").encode()
        flt = b""
        if flate:
            data, flt = zlib.compress(data), b" /Filter /FlateDecode"
        font_no = 3 + 2 * n
        objs.append(f"<< /Type /Page /Parent 2 0 R /Contents {content_no} 0 R "
                    f"/Resources << /Font << /F1 {font_no} 0 R >> >> >>".encode())
        objs.append(b"<< /Length " + str(len(data)).encode() + flt + b" >>\nstream\n" + data + b"\nendstream")
    if wide:
        objs.append(b"<< /Type /Font /Subtype /Type0 /BaseFont /X /Encoding /UniKS-UCS2-H /DescendantFonts [] >>")
    else:
        objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = b"%PDF-1.4\n"
    for i, o in enumerate(objs, 1):
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    path.write_bytes(out + b"%%EOF")


def write_sidecar(path: Path, **kw) -> None:
    base = dict(allowed_users=[], version="1.0", department="계리평가팀", category="기타",
                created_at="2026-10-01", modified_at="2026-10-10")
    base.update(kw)
    Path(str(path) + ".meta.json").write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")


# =============================================================== Office / PDF 합성 문서 생성기 (표준 라이브러리만)
_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)


def make_docx(path: Path, items: list, title: str = "", footnotes: list[str] | None = None) -> None:
    """items: ("h", 텍스트) 제목 / ("p", 텍스트) 문단 / ("pb",) 페이지 나눔 / ("rp", 텍스트) 렌더링 쪽 나눔 후 문단 /
    ("tbl", [[셀...]...]) 표 / ("del", 텍스트) 삭제된 변경 추적 문단"""
    body = []
    for it in items:
        k = it[0]
        if k == "h":
            body.append(f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>{escape(it[1])}</w:t></w:r></w:p>')
        elif k == "p":
            body.append(f"<w:p><w:r><w:t>{escape(it[1])}</w:t></w:r></w:p>")
        elif k == "pb":
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        elif k == "rp":
            body.append(f'<w:p><w:r><w:lastRenderedPageBreak/><w:t>{escape(it[1])}</w:t></w:r></w:p>')
        elif k == "del":
            body.append(f"<w:p><w:del><w:r><w:delText>{escape(it[1])}</w:delText></w:r></w:del></w:p>")
        elif k == "tbl":
            rows = "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{escape(c)}</w:t></w:r></w:p></w:tc>" for c in row)
                           + "</w:tr>" for row in it[1])
            body.append(f"<w:tbl>{rows}</w:tbl>")
    files = {
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "word/document.xml": f"<w:document {_W}><w:body>{''.join(body)}</w:body></w:document>",
        "word/styles.xml": f'<w:styles {_W}><w:style w:styleId="Heading1"><w:name w:val="heading 1"/></w:style></w:styles>',
    }
    if title:
        files["docProps/core.xml"] = ('<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                                      'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">'
                                      f"<dc:title>{escape(title)}</dc:title><dc:creator>작성자</dc:creator>"
                                      "<dcterms:created>2026-01-02T00:00:00Z</dcterms:created></cp:coreProperties>")
    if footnotes:
        files["word/footnotes.xml"] = f"<w:footnotes {_W}>" + "".join(
            f'<w:footnote w:id="{i}"><w:p><w:r><w:t>{escape(t)}</w:t></w:r></w:p></w:footnote>'
            for i, t in enumerate(footnotes, 1)) + "</w:footnotes>"
    _zip(path, files)


_A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def make_pptx(path: Path, slides: list[dict]) -> None:
    """slide: {title, body:[...], notes, hidden, footer, number, table:[[...]], br:[(a,b)], diagram:[...]}"""
    files = {"[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'}
    ids, prels = [], []
    for n, s in enumerate(slides, start=1):
        shapes = []
        if s.get("title"):
            shapes.append(f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="T"/><p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
                          f'<p:txBody><a:p><a:r><a:t>{escape(s["title"])}</a:t></a:r></a:p></p:txBody></p:sp>')
        for t in s.get("body", []):
            shapes.append(f'<p:sp><p:nvSpPr><p:cNvPr id="3" name="B"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
                          f'<p:txBody><a:p><a:r><a:t>{escape(t)}</a:t></a:r></a:p></p:txBody></p:sp>')
        for a, b in s.get("br", []):
            shapes.append(f'<p:sp><p:nvSpPr><p:cNvPr id="4" name="BR"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:txBody><a:p>'
                          f'<a:r><a:t>{escape(a)}</a:t></a:r><a:br/><a:r><a:t>{escape(b)}</a:t></a:r></a:p></p:txBody></p:sp>')
        if s.get("footer"):
            shapes.append(f'<p:sp><p:nvSpPr><p:cNvPr id="5" name="F"/><p:cNvSpPr/><p:nvPr><p:ph type="ftr"/></p:nvPr></p:nvSpPr>'
                          f'<p:txBody><a:p><a:r><a:t>{escape(s["footer"])}</a:t></a:r></a:p></p:txBody></p:sp>')
        if s.get("number"):
            shapes.append('<p:sp><p:nvSpPr><p:cNvPr id="6" name="N"/><p:cNvSpPr/><p:nvPr><p:ph type="sldNum"/></p:nvPr></p:nvSpPr>'
                          '<p:txBody><a:p><a:fld type="slidenum"><a:t>‹#›</a:t></a:fld></a:p></p:txBody></p:sp>')
        if s.get("table"):
            rows = "".join("<a:tr>" + "".join(f"<a:tc><a:txBody><a:p><a:r><a:t>{escape(c)}</a:t></a:r></a:p></a:txBody></a:tc>" for c in r)
                           + "</a:tr>" for r in s["table"])
            shapes.append(f"<p:graphicFrame><a:graphic><a:graphicData><a:tbl>{rows}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>")
        show = ' show="0"' if s.get("hidden") else ""
        files[f"ppt/slides/slide{n}.xml"] = f'<p:sld {_A}{show}><p:cSld><p:spTree>{"".join(shapes)}</p:spTree></p:cSld></p:sld>'
        rels = []
        if s.get("notes"):
            files[f"ppt/notesSlides/notesSlide{n}.xml"] = (
                f'<p:notes {_A}><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="2" name="n"/><p:cNvSpPr/><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr>'
                f'<p:txBody><a:p><a:r><a:t>{escape(s["notes"])}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:notes>')
            rels.append(f'<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide{n}.xml"/>')
        if s.get("diagram"):
            files[f"ppt/diagrams/data{n}.xml"] = ('<dgm:dataModel xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram" '
                                                  'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><dgm:ptLst>'
                                                  + "".join(f"<dgm:pt><dgm:t><a:p><a:r><a:t>{escape(t)}</a:t></a:r></a:p></dgm:t></dgm:pt>" for t in s["diagram"])
                                                  + "</dgm:ptLst></dgm:dataModel>")
            rels.append(f'<Relationship Id="rId8" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramData" Target="../diagrams/data{n}.xml"/>')
        if rels:
            files[f"ppt/slides/_rels/slide{n}.xml.rels"] = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(rels) + "</Relationships>"
        ids.append(f'<p:sldId id="{255 + n}" r:id="rId{n}"/>')
        prels.append(f'<Relationship Id="rId{n}" Type="x" Target="slides/slide{n}.xml"/>')
    files["ppt/presentation.xml"] = f"<p:presentation {_A}><p:sldIdLst>{''.join(ids)}</p:sldIdLst></p:presentation>"
    files["ppt/_rels/presentation.xml.rels"] = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(prels) + "</Relationships>"
    _zip(path, files)


def make_xlsx_raw(path: Path, sheets: dict[str, str], *, shared: str = "", styles: str = "", hidden: tuple = (),
                  date1904: bool = False) -> None:
    """sheets = {시트명: sheetData 안쪽 XML(<row>...)}"""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    sh = "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"' + (' state="hidden"' if n in hidden else "") + "/>"
                 for i, n in enumerate(sheets, 1))
    files = {
        "xl/workbook.xml": f'<workbook {ns}>' + ('<workbookPr date1904="1"/>' if date1904 else "") + f"<sheets>{sh}</sheets></workbook>",
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
            f'<Relationship Id="rId{i}" Type="x" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1)) + "</Relationships>",
    }
    for i, xml in enumerate(sheets.values(), 1):
        files[f"xl/worksheets/sheet{i}.xml"] = f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{xml}</sheetData></worksheet>'
    if shared:
        files["xl/sharedStrings.xml"] = f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{shared}</sst>'
    if styles:
        files["xl/styles.xml"] = f'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{styles}</styleSheet>'
    _zip(path, files)


def make_pdf_adv(path: Path, pages: list[list[str]], *, tounicode: bool = True, objstm: bool = False, a85: bool = False,
                 nested: bool = True, kerning: bool = False) -> None:
    """Type0 / Identity-H 글꼴 + ToUnicode CMap 을 쓰는 PDF (Word·Excel 'PDF로 저장' 결과와 같은 구조).
    pages = 쪽별 줄 목록. 각 줄은 `Td` 로 아래로 이동해 별도 줄이 된다."""
    chars = sorted({c for pg in pages for line in pg for c in line})
    code = {c: i + 1 for i, c in enumerate(chars)}

    def hexs(line: str) -> str:
        return "".join(f"{code[c]:04X}" for c in line)

    cmap = ("/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
            f"{len(chars)} beginbfchar\n" + "\n".join(f"<{code[c]:04X}> <{ord(c):04X}>" for c in chars) + "\nendbfchar\nendcmap end end")
    n = len(pages)
    objs: dict[int, bytes] = {}
    streams: dict[int, bytes] = {}
    inner = nested
    pages_root, pages_child = 2, 3
    first_page = 4
    font_no = first_page + 2 * n
    desc_no, tu_no = font_no + 1, font_no + 2
    page_nos = [first_page + 2 * i for i in range(n)]
    kids_child = " ".join(f"{p} 0 R" for p in page_nos)
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    if inner:
        objs[pages_root] = f"<< /Type /Pages /Kids [{pages_child} 0 R] /Count {n} >>".encode()
        objs[pages_child] = f"<< /Type /Pages /Parent 2 0 R /Kids [{kids_child}] /Count {n} /Resources << /Font << /F1 {font_no} 0 R >> >> >>".encode()
        parent = pages_child
    else:
        objs[pages_root] = f"<< /Type /Pages /Kids [{kids_child}] /Count {n} /Resources << /Font << /F1 {font_no} 0 R >> >> >>".encode()
        objs[pages_child] = b"<< >>"
        parent = pages_root
    for i, lines in enumerate(pages):
        ops = ["BT /F1 12 Tf 50 750 Td"]
        for j, line in enumerate(lines):
            if j:
                ops.append("0 -20 Td")
            if kerning and len(line) > 2:
                half = len(line) // 2
                ops.append(f"[<{hexs(line[:half])}> -400 <{hexs(line[half:])}>] TJ")
            else:
                ops.append(f"<{hexs(line)}> Tj")
        ops.append("ET")
        data = "\n".join(ops).encode()
        filt = b""
        if a85:
            import base64
            data, filt = base64.a85encode(zlib.compress(data), adobe=True), b"/Filter [/ASCII85Decode /FlateDecode]"
        else:
            data, filt = zlib.compress(data), b"/Filter /FlateDecode"
        objs[page_nos[i]] = f"<< /Type /Page /Parent {parent} 0 R /Contents {page_nos[i] + 1} 0 R >>".encode()
        streams[page_nos[i] + 1] = b"<< /Length %d %s >>\nstream\n" % (len(data), filt) + data + b"\nendstream"
    objs[font_no] = (f"<< /Type /Font /Subtype /Type0 /BaseFont /ABCDEF+Test /Encoding /Identity-H /DescendantFonts [{desc_no} 0 R]"
                     + (f" /ToUnicode {tu_no} 0 R" if tounicode else "") + " >>").encode()
    objs[desc_no] = b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /ABCDEF+Test /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> >>"
    if tounicode:
        z = zlib.compress(cmap.encode("latin-1", errors="ignore"))
        streams[tu_no] = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(z) + z + b"\nendstream"
    out = b"%PDF-1.5\n"
    if objstm:
        # 스트림이 아닌 객체를 객체 스트림 하나에 압축 (PDF 1.5+ 기본 동작)
        packed = sorted(objs)
        body, head, off = b"", b"", 0
        for no in packed:
            head += f"{no} {off} ".encode()
            piece = objs[no] + b"\n"
            body += piece
            off += len(piece)
        data = zlib.compress(head + body)
        out += (f"900 0 obj\n<< /Type /ObjStm /N {len(packed)} /First {len(head)} /Filter /FlateDecode /Length {len(data)} >>\nstream\n").encode() + data + b"\nendstream\nendobj\n"
        for no, s in streams.items():
            out += f"{no} 0 obj\n".encode() + s + b"\nendobj\n"
    else:
        for no in sorted({**objs, **streams}):
            out += f"{no} 0 obj\n".encode() + (objs.get(no) or streams[no]) + b"\nendobj\n"
    path.write_bytes(out + b"%%EOF")
