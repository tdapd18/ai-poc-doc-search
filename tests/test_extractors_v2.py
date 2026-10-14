"""DOCX·CSV 신규 추출과 PDF·Excel·PPT 정확도 개선 검증 (합성 문서)."""
import zlib
from pathlib import Path

import pytest

from core.extractors import (decode_text, extract, extract_csv, extract_docx, extract_pdf, extract_pptx,
                             extract_xlsx, _docx, _pptx, _xlsx, _csv, _pdf)
from core.models import InvalidDocumentError
from helpers import make_docx, make_pdf_adv, make_pptx, make_xlsx_raw

# ------------------------------------------------------------------ DOCX
def test_docx_headings_tables_pages_footnotes(tmp_path, rec):
    """입력조건: 제목·문단·페이지 나눔·표·변경 추적 삭제문·각주가 있는 DOCX
    예상결과: 제목별로 문단이 묶이고 '문단 a–b · 약 N쪽' 위치, 표는 '표 N · 행 R' + 머리글 라벨, 삭제된 문장·각주 처리, 문서 제목 속성 추출"""
    p = tmp_path / "a.docx"
    make_docx(p, [("h", "1. 결산 검증 절차"), ("p", "입력 데이터 대사를 먼저 수행한다."), ("p", "모델 실행 결과를 확인한다."),
                  ("rp", "2쪽에 걸친 문단이다."), ("del", "삭제된 비밀 문장"),
                  ("h", "2. 허용 오차"),
                  ("tbl", [["항목", "허용 오차"], ["롤포워드 대사", "1백만원"], ["CSM 변동률", "±5%"]])],
              title="결산 검증 가이드", footnotes=["각주 내용 예시"])
    ex = _docx(p.read_bytes())
    rec([s[1] for s in ex.segments])
    assert ex.props["title"] == "결산 검증 가이드" and ex.props["author"] == "작성자"
    first = ex.segments[0]
    assert first[0] == "1. 결산 검증 절차" and first[1].startswith("문단 1–3") and "약 1–2쪽" in first[1]
    assert "입력 데이터 대사" in first[2] and "삭제된 비밀 문장" not in " ".join(s[2] for s in ex.segments)
    rows = [s for s in ex.segments if s[1].startswith("표 1")]
    assert [r[1] for r in rows][:2] == ["표 1 · 행 1 · 약 2쪽", "표 1 · 행 2 · 약 2쪽"]
    assert "항목: CSM 변동률 | 허용 오차: ±5%".replace("항목: CSM 변동률", "항목: CSM 변동률") in rows[2][2]
    assert rows[1][0] == "2. 허용 오차"
    assert ("각주", "각주 1", "각주 내용 예시") in ex.segments


def test_docx_explicit_page_breaks_when_no_rendered_info(tmp_path):
    """입력조건: lastRenderedPageBreak 없이 명시적 쪽 나눔만 있는 DOCX
    예상결과: 명시적 쪽 나눔으로 '약 2쪽'을 추정"""
    p = tmp_path / "b.docx"
    make_docx(p, [("p", "첫 쪽 내용입니다."), ("pb",), ("p", "둘째 쪽 내용입니다.")])
    segs = extract_docx(p)
    assert any("약 1–2쪽" in s[1] for s in segs)


def test_docx_errors(tmp_path):
    """입력조건: 구형 OLE 시그니처의 .docx(암호화/구형), 손상 zip, 본문 없는 docx
    예상결과: 각각 암호/구형·손상·텍스트 없음 오류(InvalidDocumentError)"""
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100
    with pytest.raises(InvalidDocumentError, match="암호"):
        extract("docx", ole)
    with pytest.raises(InvalidDocumentError, match="손상"):
        extract("docx", b"garbage")
    p = tmp_path / "e.docx"
    make_docx(p, [("p", "")])
    with pytest.raises(InvalidDocumentError, match="텍스트가 없는"):
        extract_docx(p)


# ------------------------------------------------------------------ CSV / 인코딩
@pytest.mark.parametrize("enc,bom", [("utf-8", b"\xef\xbb\xbf"), ("cp949", b""), ("utf-8", b"")])
def test_csv_encodings(enc, bom, rec):
    """입력조건: 같은 한글 CSV 를 UTF-8 BOM / CP949(한국어 Excel 기본) / UTF-8 로 저장
    예상결과: 모두 올바른 한글로 읽히고 '머리글: 값' 형태, 위치는 '행 N'"""
    data = bom + "모델,실행횟수,판정\n장기보장 모델,12,적합\n연금저축 모델,8,재실행".encode(enc)
    ex = _csv(data)
    rec(f"{enc}: {ex.segments[1]}")
    assert ex.segments[1][1:] == ("행 2", "모델: 장기보장 모델 | 실행횟수: 12 | 판정: 적합")
    assert ex.segments[2][1] == "행 3" and "재실행" in ex.segments[2][2]


def test_csv_delimiters_grouping_and_errors():
    """입력조건: 세미콜론·탭 구분 CSV, 2500행 CSV, 빈 CSV
    예상결과: 구분자 자동 판별, 2000행 초과 시 10행씩 묶어 '행 a–b', 빈 파일은 오류"""
    assert _csv("가;나;다\n1;2;3".encode("utf-8")).segments[1][2] == "가: 1 | 나: 2 | 다: 3"
    assert "나: y" in _csv("가\t나\nx\ty".encode("utf-8")).segments[1][2]
    big = ("이름,값\n" + "\n".join(f"항목{i},{i}" for i in range(2500))).encode()
    segs = _csv(big).segments
    assert segs[0][1] == "행 1–10" and len(segs) == 251
    with pytest.raises(InvalidDocumentError):
        _csv(b"   \n")


def test_decode_text_detection():
    """입력조건: UTF-8, UTF-8 BOM, UTF-16, CP949, 판별 불가 바이트
    예상결과: 각 인코딩을 판별하고 판별 불가는 대체 문자로 처리(예외 없음)"""
    s = "결산 마감 일정"
    assert decode_text(s.encode("utf-8")) == (s, "utf-8")
    assert decode_text(b"\xef\xbb\xbf" + s.encode()) == (s, "utf-8-sig")
    assert decode_text(s.encode("utf-16")) == (s, "utf-16")
    assert decode_text(s.encode("cp949")) == (s, "cp949")
    assert decode_text(b"\xff\xfe\xfa\xfb\x80\x81 \xc0")[1] in ("utf-16", "cp949", "utf-8(replace)")


# ------------------------------------------------------------------ Excel 개선
def test_xlsx_dates_percent_formulas_hidden_phonetic(tmp_path, rec):
    """입력조건: 날짜 서식 셀(시리얼 값), 퍼센트, 수식 캐시 값, 오류 값, 후리가나가 있는 공유 문자열, 숨김 시트
    예상결과: 날짜는 ISO 로, 퍼센트는 %로, 수식 값은 결과값으로, 오류 값·후리가나·숨김 시트는 색인하지 않고 숨김 시트는 경고로 보고"""
    styles = ('<numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy&quot;년&quot; m&quot;월&quot;"/></numFmts>'
              '<cellXfs count="4"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="10"/><xf numFmtId="164"/></cellXfs>')
    shared = ('<si><t>항목</t></si><si><t>기준일</t></si><si><t>변동률</t></si><si><t>합계</t></si>'
              '<si><r><t>결산</t></r><rPh sb="0" eb="2"><t>케산</t></rPh></si>')
    row1 = '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c><c r="D1" t="s"><v>3</v></c></row>'
    row2 = ('<row r="2"><c r="A2" t="s"><v>4</v></c><c r="B2" s="1"><v>46309</v></c><c r="C2" s="2"><v>0.0523</v></c>'
            '<c r="D2"><f>SUM(1,2)</f><v>3</v></c><c r="E2" t="e"><v>#DIV/0!</v></c></row>')
    p = tmp_path / "x.xlsx"
    make_xlsx_raw(p, {"데이터": row1 + row2, "숨김시트": '<row r="1"><c r="A1" t="inlineStr"><is><t>비밀</t></is></c></row>'},
                  shared=shared, styles=styles, hidden=("숨김시트",))
    ex = _xlsx(p.read_bytes())
    text = ex.segments[1][2]
    rec(text)
    assert text == "항목: 결산 | 기준일: 2026-10-14 | 변동률: 5.23% | 합계: 3"
    assert "케산" not in text and "비밀" not in " ".join(s[2] for s in ex.segments)
    assert any("숨김 시트 1개" in w for w in ex.warnings)


def test_xlsx_custom_date_1904_and_missing_cell_refs(tmp_path):
    """입력조건: 1904 날짜 체계 통합 문서, 셀 주소(r) 속성이 없는 행
    예상결과: 1904 기준으로 날짜 변환, 주소가 없으면 순서대로 A,B,C 부여"""
    styles = '<cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs>'
    p = tmp_path / "y.xlsx"
    make_xlsx_raw(p, {"S": '<row><c t="inlineStr"><is><t>기준일</t></is></c><c t="inlineStr"><is><t>값</t></is></c></row>'
                          '<row><c s="1"><v>1000</v></c><c t="inlineStr"><is><t>가</t></is></c></row>'}, styles=styles, date1904=True)
    segs = extract_xlsx(p)
    assert segs[1][1] == "시트 'S' · 셀 A2:B2" and segs[1][2] == "기준일: 1906-09-27 | 값: 가"


# ------------------------------------------------------------------ PPT 개선
def test_pptx_hidden_footer_break_smartart_table_notes(tmp_path, rec):
    """입력조건: 숨김 슬라이드, 꼬리말·슬라이드 번호 자리표시자, 줄바꿈, SmartArt 텍스트, 표, 발표자 노트
    예상결과: 숨김 슬라이드는 '(숨김)' 표기, 꼬리말·번호는 제외, 줄바꿈 유지, SmartArt·표·노트 포함"""
    p = tmp_path / "s.pptx"
    make_pptx(p, [
        {"title": "개요", "body": ["첫 줄"], "footer": "사내 자료 꼬리말", "number": True, "br": [("가", "나")]},
        {"title": "비공개 슬라이드", "body": ["숨김 내용"], "hidden": True},
        {"title": "구성", "diagram": ["입력", "모델", "검증"], "table": [["항목", "값"], ["a", "1"]], "notes": "노트 내용"},
    ])
    ex = _pptx(p.read_bytes())
    rec([s[1] for s in ex.segments])
    assert [s[1] for s in ex.segments] == ["슬라이드 1", "슬라이드 2 (숨김)", "슬라이드 3"]
    s1, s3 = ex.segments[0][2], ex.segments[2][2]
    assert "꼬리말" not in s1 and "‹#›" not in s1 and "가\n나" in s1
    assert all(w in s3 for w in ("입력", "검증", "항목 | 값", "발표자 노트: 노트 내용"))


# ------------------------------------------------------------------ PDF 개선
KOR = [["결산 검증 보고서", "모델 실행 오류 E101 조치 완료"], ["둘째 쪽: 변동 분석 결과", "GoC 단위 CSM 변동률 6.2%"]]


@pytest.mark.parametrize("objstm", [False, True])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("a85", [False, True])
def test_pdf_tounicode_objstm_nested_pages(tmp_path, objstm, nested, a85, rec):
    """입력조건: Identity-H 글꼴 + ToUnicode(한글) PDF 를 객체 스트림 유무 × 중첩 페이지 트리 × ASCII85+Flate 조합으로 생성
    예상결과: 모든 조합에서 쪽 순서대로 한글 텍스트가 줄 단위로 복원됨(Word/Excel 'PDF로 저장' 구조)"""
    p = tmp_path / "t.pdf"
    make_pdf_adv(p, KOR, objstm=objstm, nested=nested, a85=a85)
    segs = extract_pdf(p)
    assert [s[1] for s in segs] == ["p.1", "p.2"]
    assert segs[0][2] == "결산 검증 보고서\n모델 실행 오류 E101 조치 완료"
    assert segs[1][2].splitlines()[1] == "GoC 단위 CSM 변동률 6.2%"
    rec(f"objstm={objstm} nested={nested} a85={a85} OK")


def test_pdf_kerning_inserts_space(tmp_path):
    """입력조건: TJ 배열의 큰 음수 커닝(단어 간격 표현)이 있는 PDF
    예상결과: 커닝 위치에 공백이 복원됨('결산검' + '증보고서' → '결산검 증보고서')"""
    p = tmp_path / "k.pdf"
    make_pdf_adv(p, [["결산검증보고서"]], kerning=True)
    assert extract_pdf(p)[0][2] == "결산검 증보고서"


def test_pdf_cid_font_without_tounicode_is_reported_not_garbled(tmp_path):
    """입력조건: ToUnicode 가 없는 Identity-H(CID) 글꼴 PDF
    예상결과: 잘못된 글자를 만들지 않고 '텍스트를 추출할 수 없습니다 (스캔본이거나 …)'로 보고"""
    q = tmp_path / "c.pdf"
    make_pdf_adv(q, [["결산 보고서"]], tounicode=False)
    with pytest.raises(InvalidDocumentError, match="텍스트를 추출할 수 없습니다.*스캔본"):
        _pdf(q.read_bytes())


def test_pdf_real_producer_embedded_font_with_tounicode(tmp_path, rec):
    """입력조건: reportlab(실제 PDF 생성 라이브러리)으로 TrueType 글꼴을 임베딩해 만든 PDF (Identity-H + ToUnicode)
    예상결과: 표준 라이브러리 추출기가 한자·영문 텍스트를 복원하고, 외부 라이브러리(pypdf)가 읽은 텍스트와 일치"""
    rl = pytest.importorskip("reportlab.pdfgen.canvas")
    pypdf = pytest.importorskip("pypdf")
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font = Path("/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf")
    if not font.exists():
        pytest.skip("테스트용 TrueType 글꼴 없음")
    pdfmetrics.registerFont(TTFont("TestJP", str(font)))
    p = tmp_path / "rl.pdf"
    c = rl.Canvas(str(p), pageCompression=1)
    c.setFont("TestJP", 12)
    c.drawString(50, 780, "決算検証 report E101")
    c.drawString(50, 760, "第二行 CSM 5%")
    c.showPage()
    c.save()
    mine = extract_pdf(p)[0][2]
    ref = pypdf.PdfReader(str(p)).pages[0].extract_text()
    rec(mine.replace("\n", " / "))
    assert "決算検証 report E101" in mine and "第二行 CSM 5%" in mine
    assert [l.strip() for l in mine.splitlines()] == [l.strip() for l in ref.splitlines() if l.strip()]


def test_pdf_flate_literal_latin_and_tj_arrays(tmp_path):
    """입력조건: 이전 형식(Helvetica 리터럴 문자열) PDF 가 새 추출기에서도 동작
    예상결과: 기존 추출 결과 유지(회귀 방지)"""
    from helpers import make_pdf
    p = tmp_path / "old.pdf"
    make_pdf(p, ["Closing error E101 (ok)"], flate=True)
    assert extract_pdf(p)[0][2] == "Closing error E101 (ok)"
