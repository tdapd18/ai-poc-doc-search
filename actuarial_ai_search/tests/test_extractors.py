import zipfile
from pathlib import Path

import pytest

from core.extractors import col_letters, extract_pdf, extract_pptx, extract_xlsx
from core.models import InvalidDocumentError
from helpers import make_pdf, make_xlsx

DATA = Path(__file__).resolve().parent.parent / "data" / "shared_folder"
XLSX = DATA / "계리평가" / "모델검증" / "모델별_검증결과_집계_2026-09.xlsx"
PPTX = DATA / "계리평가" / "교육자료" / "월말결산_킥오프_자료.pptx"
PDF = DATA / "계리평가" / "결산검증" / "결산_내부통제_점검보고서.pdf"


def test_xlsx_sheet_and_cell_locations(rec):
    """입력조건: 실제 Excel 파일(3개 시트)을 표준 라이브러리 추출기로 읽음
    예상결과: 행마다 '시트 'X' · 셀 A2:E2' 위치와 '머리글: 값' 텍스트가 만들어지고 3개 시트가 모두 포함됨"""
    segs = extract_xlsx(XLSX)
    locs = [s[1] for s in segs]
    assert {s[0] for s in segs} == {"요약", "GoC별변동", "오류내역"}
    assert "시트 '요약' · 셀 A3:E3" in locs
    row = next(t for h, l, t in segs if l == "시트 '요약' · 셀 A3:E3")
    assert "모델: 연금저축 모델" in row and "오류건수: 1" in row
    rec(f"{len(segs)}개 행 조각, 예: {locs[2]}")


def test_pptx_slide_locations_title_table_notes(rec):
    """입력조건: 실제 PowerPoint 파일(5장)
    예상결과: 슬라이드 번호 위치, 제목, 표 행, 발표자 노트가 추출됨"""
    segs = extract_pptx(PPTX)
    assert [s[1] for s in segs] == [f"슬라이드 {i}" for i in range(1, 6)]
    s3 = segs[2]
    assert s3[0] == "RAFM 모델 실행 오류 사전 점검" and "E101" in s3[2] and "발표자 노트:" in s3[2]
    assert "CSM 변동률 | 전월 대비 ±5% 초과" in segs[3][2]
    rec("슬라이드 5장, 3번 슬라이드 노트 포함")


def test_pdf_page_locations(rec):
    """입력조건: 실제 PDF 파일(3쪽, 한글, UniKS-UCS2-H 인코딩)
    예상결과: 쪽 번호(p.1~p.3) 위치와 한글 텍스트가 추출됨"""
    segs = extract_pdf(PDF)
    assert [s[1] for s in segs] == ["p.1", "p.2", "p.3"]
    assert "E101" in segs[1][2] and "개선 과제" in segs[2][2] and "점검 목적" in segs[0][2]
    rec("3쪽 추출, p.2 에 E101")


def test_pdf_cross_check_page_count_with_pypdf():
    """입력조건: 샘플 PDF 를 외부 라이브러리(pypdf, 개발용)로도 열어 쪽수 비교
    예상결과: 같은 3쪽 — 샘플이 유효한 PDF 이고 추출기의 쪽 구분이 정확함"""
    pypdf = pytest.importorskip("pypdf")
    assert len(pypdf.PdfReader(str(PDF)).pages) == len(extract_pdf(PDF)) == 3


@pytest.mark.parametrize("flate", [False, True])
@pytest.mark.parametrize("wide", [False, True])
def test_pdf_encodings(tmp_path, flate, wide):
    """입력조건: 손으로 만든 PDF — 비압축/Flate 압축 × 1바이트 문자열/2바이트 코드 16진 문자열
    예상결과: 모든 조합에서 쪽별 텍스트 추출"""
    p = tmp_path / "t.pdf"
    text = ["결산 오류 E101", "second page 한글"] if wide else ["Closing error E101 (ok)", "second page"]
    make_pdf(p, text, flate=flate, wide=wide)
    segs = extract_pdf(p)
    assert [s[1] for s in segs] == ["p.1", "p.2"] and text[0] in segs[0][2] and text[1] in segs[1][2]


def test_xlsx_inline_strings_and_numeric_header(tmp_path):
    """입력조건: sharedStrings 없이 inlineStr 만 쓰는 xlsx, 첫 행이 숫자인 시트
    예상결과: 오류 없이 읽고, 숫자 첫 행은 머리글로 보지 않음(값만 이어 붙임)"""
    p = tmp_path / "a.xlsx"
    make_xlsx(p, {"S": [["이름", "값"], ["가", 1]], "N": [[1, 2, 3], [4, 5, 6]]}, shared=False)
    segs = extract_xlsx(p)
    assert ("S", "시트 'S' · 셀 A2:B2", "이름: 가 | 값: 1") in segs
    assert ("N", "시트 'N' · 셀 A2:C2", "4 | 5 | 6") in segs


def test_col_letters():
    """입력조건: 열 번호 1, 26, 27, 702
    예상결과: A, Z, AA, ZZ"""
    assert [col_letters(i) for i in (1, 26, 27, 702)] == ["A", "Z", "AA", "ZZ"]


def test_corrupt_and_unsupported_files_raise_invalid(tmp_path, rec):
    """입력조건: 손상 xlsx/pptx, 빈 시트 xlsx, PDF 아님, 텍스트 없는 PDF, 암호화 PDF, DTD 포함 XML
    예상결과: 모두 InvalidDocumentError(본문 내용 없는 사유)로 처리되어 앱이 중단되지 않음"""
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"not a zip")
    with pytest.raises(InvalidDocumentError):
        extract_xlsx(bad)
    with pytest.raises(InvalidDocumentError):
        extract_pptx(bad)
    empty = tmp_path / "empty.xlsx"
    make_xlsx(empty, {"S": []})
    with pytest.raises(InvalidDocumentError):
        extract_xlsx(empty)
    notpdf = tmp_path / "x.pdf"
    notpdf.write_bytes(b"hello")
    with pytest.raises(InvalidDocumentError, match="PDF 형식"):
        extract_pdf(notpdf)
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Page >>\nendobj\n%%EOF")
    with pytest.raises(InvalidDocumentError, match="텍스트를 추출할 수 없습니다"):
        extract_pdf(scan)
    enc = tmp_path / "enc.pdf"
    enc.write_bytes(b"%PDF-1.4\ntrailer << /Encrypt 5 0 R >>")
    with pytest.raises(InvalidDocumentError, match="암호화"):
        extract_pdf(enc)
    xxe = tmp_path / "xxe.xlsx"
    with zipfile.ZipFile(xxe, "w") as z:
        z.writestr("xl/workbook.xml", '<!DOCTYPE x [<!ENTITY a "b">]><workbook/>')
    with pytest.raises(InvalidDocumentError, match="DTD"):
        extract_xlsx(xxe)
    rec("손상/빈/비PDF/스캔/암호화/DTD 모두 InvalidDocumentError")


def test_zip_member_limit(tmp_path):
    """입력조건: 구성요소 3000개짜리 압축 파일(압축 폭탄 유형)
    예상결과: 크기/개수 제한으로 거부"""
    p = tmp_path / "bomb.xlsx"
    with zipfile.ZipFile(p, "w") as z:
        for i in range(3000):
            z.writestr(f"f{i}.txt", "x")
    with pytest.raises(InvalidDocumentError, match="크기 제한"):
        extract_xlsx(p)
