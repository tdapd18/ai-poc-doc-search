"""키워드 기반 통합 검색 엔진 + 관련성 점수 + 권한 필터 + 캐시.

=== 검색 순서 (보안상 중요) ===
1. 마지막 동기화에 성공한 저장소의 문서만 후보로 삼는다 (오류 저장소는 제외하고 사용자에게 알린다).
2. **접근권한 필터를 점수 계산보다 먼저** 적용한다. 비인가 문서는 점수 계산, 결과 개수, 통계,
   캐시, AI 컨텍스트 어디에도 등장하지 않는다.
3. 카테고리/저장소 필터 적용.
4. 문단 단위 점수 → 문서 점수 → 정렬 → 상위 K개(최대 5).

=== 점수 규칙 (SCORING.md 와 동일) ===
개념(concept) = 질의 토큰 1개 + 그 동의어. 개념마다 문서 안에서 가장 잘 맞는 용어 1개의 가중치 w 를 쓴다
(원 질의어 1.0, 동의어 0.6, 일반어 0.3).

  문단 점수 raw  = Σ_개념 [ 본문 w·min(출현횟수,3)  +  소제목 일치 3·w ]  +  어구 보너스
  어구 보너스    = 질의에서 연속된 두 토큰이 본문에 같은 순서로 붙어 나오면 +1.5 (쌍마다)
  문단 점수      = raw × (0.5 + 0.5 × 문단 적합도)         # 적합도 = 제목∪소제목∪본문에서 일치한 개념 비율
  제목 점수      = Σ_개념 5·w (문서 제목에 일치한 개념)
  문서 점수      = 제목 점수 + 최고 문단 점수 + 0.25 × (그 다음 문단 최대 3개 점수 합)
  문서 적합도    = 문서 전체(제목·소제목·본문)에서 일치한 개념 비율
  결과 포함 조건 = 문서 적합도 ≥ 0.5 (일반어만 일치하는 문서는 제외) 그리고 문서 점수 ≥ 1.0
  정렬           = 문서 점수 내림차순 → 최종 수정일 최신순 → 문서 ID
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.access_control import AccessController, User
from core.indexer import Indexer
from core.logging_utils import get_logger, log_event
from core.models import CATEGORIES, Chunk, Document
from core.text_utils import Concept, QueryAnalysis, SearchDictionary, analyze_query, normalize_text

MIN_DOC_COVERAGE = 0.5
MIN_DOC_SCORE = 1.0
MAX_TOP_K = 5
TITLE_W, HEADING_W, BODY_CAP, PHRASE_BONUS = 5.0, 3.0, 3, 1.5

_log = get_logger()


@dataclass(frozen=True)
class Passage:
    chunk_seq: int
    heading: str
    text: str
    score: float
    flagged: bool = False
    flag_reason: str = ""
    matched_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchResult:
    doc_id: str
    title: str
    source_key: str
    source_system: str
    category: str
    version: str
    modified_at: str
    department: str
    location: str
    location_detail: str
    content_hash: str
    score: float
    coverage: float
    passages: tuple[Passage, ...]


@dataclass
class SearchResponse:
    query: str
    status: str  # ok | empty_query | no_results | no_sources | denied
    message: str = ""
    results: list[SearchResult] = field(default_factory=list)
    unavailable_sources: list[str] = field(default_factory=list)  # 오류로 검색에서 제외된 저장소 표시명
    analysis: QueryAnalysis | None = None
    total_matched: int = 0  # 권한 필터 이후 일치 문서 수 (top_k 로 잘리기 전)
    generation: int = 0
    from_cache: bool = False


def _count(text: str, term: str) -> int:
    return text.count(term) if term else 0


class SearchEngine:
    def __init__(self, indexer: Indexer, access: AccessController, dictionary: SearchDictionary):
        self.indexer = indexer
        self.access = access
        self.dictionary = dictionary
        self._cache: dict[tuple, tuple[int, SearchResponse]] = {}

    # -- 캐시 ----------------------------------------------------------------
    def invalidate_cache(self) -> None:
        self._cache.clear()

    def _revalidate(self, user: User | None, response: SearchResponse) -> bool:
        """캐시된 결과의 모든 문서가 지금도 존재·열람 가능·동일 내용인지 재검증."""
        for r in response.results:
            doc = self.indexer.get_document(r.doc_id)
            if doc is None or not self.access.can_access(user, doc):
                return False
            if self.indexer.content_hash_of(r.doc_id) != r.content_hash:
                return False
        return True

    # -- 검색 ----------------------------------------------------------------
    def search(self, user: User | None, query: str, categories: list[str] | None = None,
               sources: list[str] | None = None, top_k: int = MAX_TOP_K) -> SearchResponse:
        top_k = max(1, min(MAX_TOP_K, top_k))
        generation = self.indexer.get_generation()
        unavailable = [s["source_label"] for s in self.indexer.source_statuses() if s["status"] != "ok"]

        if user is None or self.access.get_user(user.user_id) is None:
            return SearchResponse(query, "denied", "확인되지 않은 사용자입니다. 사용자를 선택해 주세요.",
                                  generation=generation)
        if not query or not query.strip():
            return SearchResponse(query or "", "empty_query", "검색어를 입력해 주세요.", generation=generation)

        cache_key = (user.user_id, normalize_text(query.strip(), self.dictionary),
                     tuple(sorted(categories or [])), tuple(sorted(sources or [])), top_k)
        cached = self._cache.get(cache_key)
        if cached:
            if cached[0] == generation and self._revalidate(user, cached[1]):
                hit = cached[1]
                return SearchResponse(**{**hit.__dict__, "from_cache": True})
            del self._cache[cache_key]  # 색인이 바뀌었거나 재검증 실패 → 폐기 후 재계산

        response = self._search_uncached(user, query, categories, sources, top_k, unavailable, generation)
        self._cache[cache_key] = (generation, response)
        # 로그: 검색어/본문은 기록하지 않는다 (길이와 건수만)
        log_event(_log, "search", user=user.user_id, query_len=len(query), status=response.status,
                  results=len(response.results), cache=False)
        return response

    def _search_uncached(self, user, query, categories, sources, top_k, unavailable, generation) -> SearchResponse:
        statuses = self.indexer.source_statuses()
        if not any(s["status"] == "ok" for s in statuses):
            msg = ("검색 가능한 저장소가 없습니다. 저장소 연결 상태를 확인한 뒤 '색인 갱신'을 실행해 주세요."
                   if statuses else "연결된 저장소가 없습니다. '색인 갱신'을 먼저 실행해 주세요.")
            return SearchResponse(query, "no_sources", msg, unavailable_sources=unavailable, generation=generation)
        docs = self.indexer.list_documents(searchable_only=True)
        # 1) 권한 필터 (점수 계산 이전)
        docs = self.access.filter_documents(user, docs)
        # 2) 사용자 필터
        if categories:
            docs = [d for d in docs if d.category in categories]
        if sources:
            docs = [d for d in docs if d.source_key in sources]

        analysis = analyze_query(query, self.dictionary)
        if not analysis.concepts:
            return SearchResponse(query, "no_results", "검색어에서 의미 있는 단어를 찾지 못했습니다. "
                                  "업무 용어를 포함해 다시 질문해 주세요.", analysis=analysis,
                                  unavailable_sources=unavailable, generation=generation)

        scored: list[SearchResult] = []
        for doc in docs:
            res = self._score_document(doc, analysis)
            if res:
                scored.append(res)
        scored.sort(key=lambda r: (-r.score, _neg_date(r.modified_at), r.doc_id))
        total = len(scored)
        if not scored:
            return SearchResponse(query, "no_results", "질문과 관련된 문서를 찾지 못했습니다.", analysis=analysis,
                                  unavailable_sources=unavailable, generation=generation)
        return SearchResponse(query, "ok", results=scored[:top_k], analysis=analysis, total_matched=total,
                              unavailable_sources=unavailable, generation=generation)

    # -- 점수 계산 -----------------------------------------------------------
    def _best_variant(self, concept: Concept, text: str) -> tuple[float, int, str]:
        """text 안에서 개념의 가장 높은 가중치 용어와 (가중치, 출현횟수, 용어)를 반환."""
        best = (0.0, 0, "")
        for term, w in concept.variants:
            n = _count(text, term)
            if n and w > best[0]:
                best = (w, n, term)
        return best

    def _score_document(self, doc: Document, analysis: QueryAnalysis) -> SearchResult | None:
        concepts = analysis.concepts
        core_concepts = [c for c in concepts if not c.generic] or concepts
        title = normalize_text(doc.title, self.dictionary)
        chunks = self.indexer.get_chunks(doc.doc_id)

        title_score, title_hit = 0.0, set()
        for c in concepts:
            w, n, _ = self._best_variant(c, title)
            if n:
                title_score += TITLE_W * w
                title_hit.add(c.term)

        doc_hit = set(title_hit)
        chunk_scores: list[tuple[float, Chunk, tuple[str, ...]]] = []
        for ch in chunks:
            text = normalize_text(ch.text, self.dictionary)
            heading = normalize_text(ch.heading, self.dictionary)
            raw, hit, terms = 0.0, set(), []
            for c in concepts:
                w_b, n_b, t_b = self._best_variant(c, text)
                w_h, n_h, t_h = self._best_variant(c, heading)
                if n_b:
                    raw += w_b * min(n_b, BODY_CAP)
                    terms.append(t_b)
                if n_h:
                    raw += HEADING_W * w_h
                    terms.append(t_h)
                if n_b or n_h or c.term in title_hit:
                    hit.add(c.term)
            toks = analysis.tokens
            for a, b in zip(toks, toks[1:]):
                if f"{a} {b}" in text:
                    raw += PHRASE_BONUS
            doc_hit |= hit
            cov = len({c.term for c in core_concepts} & hit) / len(core_concepts)
            if raw > 0:
                chunk_scores.append((raw * (0.5 + 0.5 * cov), ch, tuple(dict.fromkeys(terms))))

        doc_cov = len({c.term for c in core_concepts} & doc_hit) / len(core_concepts)
        chunk_scores.sort(key=lambda x: (-x[0], x[1].seq))
        best = chunk_scores[0][0] if chunk_scores else 0.0
        rest = sum(s for s, _, _ in chunk_scores[1:4])
        score = title_score + best + 0.25 * rest
        if doc_cov < MIN_DOC_COVERAGE or score < MIN_DOC_SCORE:
            return None
        passages = tuple(
            Passage(ch.seq, ch.heading, ch.text, round(s, 2), ch.flagged, ch.flag_reason, terms)
            for s, ch, terms in chunk_scores[:2]
        )
        return SearchResult(
            doc_id=doc.doc_id, title=doc.title, source_key=doc.source_key, source_system=doc.source_system,
            category=doc.category, version=doc.version, modified_at=doc.modified_at, department=doc.department,
            location=doc.location, location_detail=doc.location_detail, content_hash=doc.content_hash(),
            score=round(score, 1), coverage=round(doc_cov, 2), passages=passages,
        )

    # -- 목록/미리보기 (권한 검증 포함) -------------------------------------
    def list_visible_documents(self, user: User | None, categories: list[str] | None = None,
                               sources: list[str] | None = None) -> list[Document]:
        docs = self.access.filter_documents(user, self.indexer.list_documents(searchable_only=True))
        if categories:
            docs = [d for d in docs if d.category in categories]
        if sources:
            docs = [d for d in docs if d.source_key in sources]
        return docs

    def open_document(self, user: User | None, doc_id: str) -> tuple[Document, list[Chunk]] | None:
        """원문 미리보기. 문서가 없거나 권한이 없거나 저장소가 검색 불가 상태면 None (사유를 구분하지 않는다)."""
        doc = self.indexer.get_document(doc_id)
        if doc is None or not self.access.can_access(user, doc):
            return None
        statuses = {s["source_key"]: s["status"] for s in self.indexer.source_statuses()}
        if statuses.get(doc.source_key) != "ok":
            return None
        return doc, self.indexer.get_chunks(doc_id)


def _neg_date(d: str) -> str:
    """최신 날짜가 먼저 오도록 문자열 정렬 키를 뒤집는다."""
    return "".join(chr(0x10FFFF - ord(ch)) for ch in d)


def highlight_terms(text: str, terms: tuple[str, ...]) -> str:
    """일치 용어를 **굵게** 표시 (마크다운). 입력 텍스트는 호출 측에서 이스케이프한다."""
    out = text
    for t in sorted({t for t in terms if t and len(t) >= 2}, key=len, reverse=True):
        out = re.sub(re.escape(t), lambda m: f"**{m.group(0)}**", out, flags=re.IGNORECASE)
    return out


__all__ = ["SearchEngine", "SearchResponse", "SearchResult", "Passage", "CATEGORIES", "highlight_terms"]
