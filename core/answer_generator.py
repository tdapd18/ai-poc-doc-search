"""RAG 답변 생성.

모드 A (local, 기본) : 외부 AI 없이 검색된 원문 문단과 출처를 보여준다. AI 생성 답변이 아니다.
모드 B (ai)          : 권한 검증을 통과한 근거 문단만 LLM 인터페이스에 전달하고, 출처 번호를 검증한다.
                       실패/근거 부족 시 확인 불가 안내 또는 로컬 검색 모드 결과로 되돌린다.

보안 원칙
- 근거 문단은 생성 직전에 **다시** 권한·내용 해시를 검증한다 (검색 이후 권한이 회수된 경우 차단).
- 지시문 의심 문단(flagged)은 AI 에 전달하지 않는다. 문서 속 문장은 데이터일 뿐 명령이 아니다.
- Mock LLM 응답은 "AI 생성 답변"이라고 표시하지 않는다 (is_ai_generated=False, is_mock=True).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.access_control import AccessController, User
from core.indexer import Indexer
from core.llm_client import Evidence, LLMClient, LLMError, LLMRequest
from core.logging_utils import get_logger, log_event
from core.search_engine import SearchResponse

AI_MIN_TOP_SCORE = 4.0  # 최고 문서 점수가 이보다 낮으면 근거 부족으로 본다
MAX_EVIDENCES = 6
_log = get_logger()
_CITE_RE = re.compile(r"\[(\d{1,2})\]")

LOCAL_NOTICE = "로컬 검색 모드: 아래는 AI가 생성한 답변이 아니라, 권한이 있는 문서에서 찾은 관련 원문 문단입니다."
INSUFFICIENT_TEXT = "확인 불가: 접근 가능한 문서에서 질문에 답할 충분한 근거를 찾지 못했습니다."


@dataclass(frozen=True)
class Citation:
    number: int
    doc_id: str
    title: str
    source_system: str
    version: str
    modified_at: str
    location: str
    location_detail: str
    chunk_seq: int
    heading: str
    text: str
    flagged: bool = False
    flag_reason: str = ""
    content_hash: str = ""
    loc: str = ""


@dataclass
class AnswerResult:
    mode: str  # local | ai
    status: str  # ok | no_results | insufficient | fallback
    notice: str
    answer_text: str = ""  # AI/Mock 모드에서만 채워짐
    citations: list[Citation] = field(default_factory=list)
    is_ai_generated: bool = False  # 실제 생성형 AI 가 만든 답일 때만 True
    is_mock: bool = False
    llm_label: str = ""
    fallback_reason: str = ""


class AnswerGenerator:
    def __init__(self, indexer: Indexer, access: AccessController, llm: LLMClient):
        self.indexer = indexer
        self.access = access
        self.llm = llm

    # -- 근거 수집 (권한 재검증 포함) ---------------------------------------
    def collect_citations(self, user: User | None, response: SearchResponse, limit: int = MAX_EVIDENCES) -> list[Citation]:
        cites: list[Citation] = []
        for r in response.results:
            doc = self.indexer.get_document(r.doc_id)
            if doc is None or not self.access.verify(user, doc):
                continue  # 검색 이후 삭제/권한 회수 — 생성 직전 OS 재검증
            if self.indexer.content_hash_of(doc.doc_id) != r.content_hash:
                continue  # 검색 이후 내용 변경 → 오래된 근거 사용 금지
            for p in r.passages:
                cites.append(Citation(
                    number=len(cites) + 1, doc_id=doc.doc_id, title=doc.title, source_system=doc.source_system,
                    version=doc.version, modified_at=doc.modified_at, location=doc.location,
                    location_detail=doc.location_detail, chunk_seq=p.chunk_seq, heading=p.heading, text=p.text,
                    flagged=p.flagged, flag_reason=p.flag_reason, content_hash=r.content_hash, loc=p.loc))
                if len(cites) >= limit:
                    return cites
        return cites

    # -- 모드 A -------------------------------------------------------------
    def local_answer(self, user: User | None, response: SearchResponse) -> AnswerResult:
        if response.status != "ok":
            return AnswerResult("local", "no_results", LOCAL_NOTICE)
        cites = self.collect_citations(user, response)
        if not cites:
            return AnswerResult("local", "no_results", LOCAL_NOTICE)
        return AnswerResult("local", "ok", LOCAL_NOTICE, citations=cites)

    # -- 모드 B -------------------------------------------------------------
    def ai_answer(self, user: User | None, question: str, response: SearchResponse) -> AnswerResult:
        label = _llm_label(self.llm)
        if response.status != "ok":
            return AnswerResult("ai", "no_results", "AI 답변 모드", llm_label=label, is_mock=self.llm.is_mock)
        cites = self.collect_citations(user, response)
        usable = [c for c in cites if not c.flagged]  # 지시문 의심 문단은 모델에 전달하지 않는다
        top_score = response.results[0].score if response.results else 0.0
        if not usable or top_score < AI_MIN_TOP_SCORE:
            return AnswerResult("ai", "insufficient", "AI 답변 모드", answer_text=INSUFFICIENT_TEXT,
                                citations=cites, llm_label=label, is_mock=self.llm.is_mock)
        # 근거 번호를 1..n 으로 다시 매긴다 (모델에 전달되는 번호 = 화면에 표시되는 번호)
        numbered = [Citation(**{**c.__dict__, "number": i + 1}) for i, c in enumerate(usable)]
        request = LLMRequest(question, tuple(Evidence(c.number, c.title, c.version, c.text) for c in numbered))
        try:
            raw = self.llm.generate(request)
        except LLMError as exc:
            return self._fallback(user, response, f"AI 연결 실패: {exc}", label)
        except Exception as exc:  # 어떤 모델 오류도 앱을 중단시키지 않는다
            return self._fallback(user, response, f"AI 연결 실패 ({type(exc).__name__})", label)

        answer = (raw or "").strip()
        if not answer or "확인 불가" in answer and not _CITE_RE.search(answer):
            return AnswerResult("ai", "insufficient", "AI 답변 모드", answer_text=INSUFFICIENT_TEXT,
                                citations=numbered, llm_label=label, is_mock=self.llm.is_mock)
        cited = {int(n) for n in _CITE_RE.findall(answer)}
        if not cited:
            return self._fallback(user, response, "출처 번호가 없는 답변은 사용할 수 없습니다", label)
        if not cited <= {c.number for c in numbered}:
            return self._fallback(user, response, "존재하지 않는 출처 번호가 포함된 답변은 사용할 수 없습니다", label)
        log_event(_log, "ai_answer", citations=len(numbered), mock=self.llm.is_mock)
        return AnswerResult(
            "ai", "ok", "AI 답변 모드", answer_text=answer,
            citations=[c for c in numbered if c.number in cited] or numbered,
            is_ai_generated=self.llm.is_real, is_mock=self.llm.is_mock, llm_label=label)

    def _fallback(self, user: User | None, response: SearchResponse, reason: str, label: str) -> AnswerResult:
        local = self.local_answer(user, response)
        local.status = "fallback" if local.status == "ok" else local.status
        local.fallback_reason = reason + " — 로컬 검색 모드 결과를 표시합니다."
        local.llm_label = label
        return local

    def answer(self, user: User | None, question: str, response: SearchResponse, mode: str = "local") -> AnswerResult:
        if mode == "ai":
            return self.ai_answer(user, question, response)
        return self.local_answer(user, response)


def _llm_label(llm: LLMClient) -> str:
    if llm.is_mock:
        return "Mock LLM (구조 테스트용 규칙 기반 — 실제 생성형 AI 아님)"
    if llm.is_real:
        return f"LLM: {llm.name}"
    return f"LLM 미연결 ({llm.name})"
