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
