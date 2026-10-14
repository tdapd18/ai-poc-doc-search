"""합성 Windows 공유 픽스처 — 실제 회사 자료 없이 Windows 공유폴더의 특성을 모사한다.

모든 내용은 가상이다. UNC 루트는 예약 도메인(.invalid)이며 실제로 접속되지 않는다(MappedFS 가 임시 폴더에 매핑).
모사하는 Windows/공유폴더 특성: 한글·공백·특수문자 이름, 대소문자 다른 확장자(.PPTX), 깊은 폴더와 긴 경로,
같은 이름 다른 폴더, Office 임시 잠금 파일(~$), Thumbs.db/desktop.ini, 구형 Office(OLE)·암호화 Office,
손상 파일, 0바이트, 한도 초과 파일, CP949 텍스트/CSV, 접근 거부 폴더·파일.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from core.fs import MappedFS
from helpers import make_docx, make_pdf_adv, make_pptx, make_xlsx_raw

UNC_ROOT = "\\\\fs-corp01.example.invalid\\계리평가팀"
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 512
PHRASE = "고유검증문구XYZ"  # 삭제 후 색인 파일에 남지 않는지 확인하는 표식


def unc(rel: str) -> str:
    return UNC_ROOT + "\\" + rel.replace("/", "\\")


@dataclass
class WinShare:
    local: Path
    fs: MappedFS
    rel: dict[str, str] = field(default_factory=dict)  # 키 → 상대 경로(\ 구분)

    def path(self, key: str) -> Path:
        return self.local / self.rel[key].replace("\\", os.sep)

    def unc(self, key: str) -> str:
        return unc(self.rel[key])

    def touch(self, key: str, when: str = "2026-10-12") -> None:
        import datetime as dt
        ts = dt.datetime.fromisoformat(when + "T12:00:00").timestamp()
        os.utime(self.path(key), (ts, ts))


def build_windows_share(root: Path) -> WinShare:
    local = root / "winshare"
    local.mkdir(parents=True)
    w = WinShare(local, MappedFS({UNC_ROOT: local}))

    def put(key: str, rel: str, writer):
        p = local / rel.replace("\\", os.sep)
        p.parent.mkdir(parents=True, exist_ok=True)
        writer(p)
        w.rel[key] = rel

    # --- 정상 업무문서 -------------------------------------------------------
    put("docx", "결산\\2026년 9월\\IFRS17 결산 검증 가이드_v2.1.docx", lambda p: make_docx(
        p, [("h", "1. 검증 절차"), ("p", f"입력 데이터 대사를 먼저 수행한다. {PHRASE}"), ("p", "모델 실행 결과를 확인한다."),
            ("h", "2. 허용 오차"), ("tbl", [["항목", "허용 오차"], ["롤포워드 대사", "1백만원"], ["CSM 변동률", "±5%"]])],
        title="IFRS17 결산 검증 가이드"))
    styles = ('<cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs>')
    put("xlsx", "결산\\2026년 9월\\모델별_검증결과_집계 (최종).xlsx", lambda p: make_xlsx_raw(
        p, {"요약": '<row r="1"><c r="A1" t="inlineStr"><is><t>모델</t></is></c><c r="B1" t="inlineStr"><is><t>기준일</t></is></c><c r="C1" t="inlineStr"><is><t>판정</t></is></c></row>'
                  '<row r="2"><c r="A2" t="inlineStr"><is><t>연금저축 모델</t></is></c><c r="B2" s="1"><v>46309</v></c><c r="C2" t="inlineStr"><is><t>적합 (E101 재실행 후)</t></is></c></row>'},
        styles=styles))
    put("pptx", "결산\\월말결산 킥오프.PPTX", lambda p: make_pptx(
        p, [{"title": "월말 결산 킥오프", "body": ["10월 30일 데이터 마감"]},
            {"title": "RAFM 오류 사전 점검", "body": ["입력 파일 도착 확인 E101 예방"], "notes": "메모리 E207 주의"}]))
    put("pdf", "결산\\내부통제 점검보고서.pdf", lambda p: make_pdf_adv(
        p, [["IFRS17 결산 내부통제 점검 보고서", "점검 목적"], ["모델 실행 오류 E101 조치 완료", "개선 과제"]]))
    put("csv", "데이터\\GoC_변동_2026-09.csv", lambda p: p.write_bytes(
        "GoC,기초 CSM,기말 CSM,변동률\nGoC-A01,1200,1197,-0.3%\nGoC-C07,640,680,6.2%".encode("cp949")))
    put("txt_cp949", "데이터\\메모.txt", lambda p: p.write_bytes("결산 마감 전 확인할 사항을 정리한 가상의 메모입니다.\n두 번째 줄입니다.".encode("cp949")))
    put("md_plain", "모델\\RAFM_오류대응_FAQ.md", lambda p: p.write_text(
        "# RAFM 오류 대응\n\n## E101\n\n입력 파일을 찾지 못했을 때 발생합니다. 파일 경로와 날짜 접미사를 확인합니다.\n", encoding="utf-8"))
    put("md_front", "모델\\front.md", lambda p: p.write_text(
        "---\ndoc_id: MD-777\ntitle: 머리말 있는 문서\ncategory: RAFM\nversion: 9.9\ncreated_at: 2026-01-01\nmodified_at: 2026-02-02\n"
        "department: 모델팀\nlocation: x\n---\n# 머리말 있는 문서\n\n머리말이 있는 마크다운 문서의 본문 내용입니다 충분히 깁니다.\n", encoding="utf-8"))
    put("same_a", "A\\보고서.txt", lambda p: p.write_text("A 폴더의 보고서 본문입니다 충분히 긴 문장으로 작성합니다.", encoding="utf-8"))
    put("same_b", "B\\보고서.txt", lambda p: p.write_text("B 폴더의 보고서 본문입니다 충분히 긴 문장으로 작성합니다.", encoding="utf-8"))
    put("special", "결산 [최종] #1 & 검토.txt", lambda p: p.write_text("특수문자가 들어간 이름의 문서 본문입니다 충분히 길게 씁니다.", encoding="utf-8"))
    deep_dirs = "\\".join(f"폴더이름_이십오자가량의긴이름{i:02d}" for i in range(1, 13))  # 12단계 → UNC 경로 260자 초과
    put("deep", f"깊은\\{deep_dirs}\\깊은문서.txt",
        lambda p: p.write_text("아주 깊은 폴더에 있는 문서의 본문입니다 충분히 길게 작성합니다.", encoding="utf-8"))
    # --- 제외·미지원·구형 ----------------------------------------------------
    put("lock", "결산\\2026년 9월\\~$IFRS17 결산 검증 가이드_v2.1.docx", lambda p: p.write_bytes(b"\x00" * 162))
    put("thumbs", "결산\\Thumbs.db", lambda p: p.write_bytes(b"thumb"))
    put("desktop", "결산\\desktop.ini", lambda p: p.write_text("[.ShellClassInfo]", encoding="utf-8"))
    put("hidden", "결산\\.숨김메모.txt", lambda p: p.write_text("숨김 파일 본문입니다 충분히 길게 작성합니다.", encoding="utf-8"))
    put("image", "이미지\\사진.png", lambda p: p.write_bytes(b"\x89PNG\r\n"))
    put("doc_legacy", "구형\\옛날 결산문서.doc", lambda p: p.write_bytes(OLE))
    put("xls_legacy", "구형\\옛날 표.xls", lambda p: p.write_bytes(OLE))
    # --- 오류 파일 -----------------------------------------------------------
    put("encrypted", "보안\\암호화된 문서.docx", lambda p: p.write_bytes(OLE))
    put("corrupt", "보안\\깨진 집계.xlsx", lambda p: p.write_bytes(b"not a zip at all"))
    put("empty", "보안\\빈 메모.txt", lambda p: p.write_bytes(b""))
    # --- 접근 제어 시험용 ----------------------------------------------------
    put("secret_docx", "기밀\\인사 평가표.docx", lambda p: make_docx(p, [("p", "기밀 문서의 본문입니다 충분히 길게 작성합니다.")], title="인사 평가표"))
    put("hidden_dir_file", "목록거부\\안쪽 문서.txt", lambda p: p.write_text("목록 권한이 없는 폴더 안의 문서 본문입니다 충분히.", encoding="utf-8"))
    for key in ("docx", "xlsx", "pptx", "pdf", "csv", "txt_cp949", "md_plain", "md_front", "same_a", "same_b", "special", "deep"):
        w.touch(key)
    w.touch("docx", "2026-10-09")
    return w


def normal_keys() -> list[str]:
    """정상적으로 색인되어야 하는 문서 키(접근 제어 대상 제외)."""
    return ["docx", "xlsx", "pptx", "pdf", "csv", "txt_cp949", "md_plain", "md_front", "same_a", "same_b", "special", "deep"]
