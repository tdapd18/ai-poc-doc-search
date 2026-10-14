"""키워드 기반 통합 검색 엔진 + 관련성 점수 + 권한 필터 + 캐시.

=== 검색 순서 (보안상 중요) ===
1. 마지막 동기화에 성공한 저장소의 문서만 후보로 삼는다 (오류 저장소는 제외하고 사용자에게 알린다).
2. **접근권한 필터를 점수 계산보다 먼저** 적용한다. 비인가 문서는 점수 계산, 결과 개수, 통계,
   필터별 건수, 캐시, AI 컨텍스트 어디에도 등장하지 않는다.
3. 사용자 필터: 분류 / 저장소 / 위치(공유폴더별) / 문서 유형 / 수정일 범위.
4. 검색 대상(scope): all=파일명·제목+본문, name=파일명·제목만, body=본문만.
5. 문단 점수 → 문서 점수 → 정렬(관련도/수정일/파일명/형식/경로) → 상위 K개(기본 5, 최대 20).

=== 점수 규칙 (docs/DESIGN.md 와 동일) ===
개념(concept) = 질의 토큰 1개 + 그 동의어. 개념마다 문서 안에서 가장 잘 맞는 용어 1개의 가중치 w 를 쓴다
(원 질의어 1.0, 동의어 0.6, 일반어 0.3).

  문단 점수 raw  = Σ_개념 [ 본문 w·min(출현횟수,3)  +  소제목 일치 3·w ]  +  어구 보너스
  어구 보너스    = 질의에서 연속된 두 토큰이 본문에 같은 순서로 붙어 나오면 +1.5 (쌍마다)
  문단 점수      = raw × (0.5 + 0.5 × 문단 적합도)         # 적합도 = 제목∪소제목∪본문에서 일치한 개념 비율
  제목 점수      = Σ_개념 5·w (문서 제목 또는 파일명에 일치; 파일명 검색 대상일 때만)
  문서 점수      = 제목 점수 + 최고 문단 점수 + 0.25 × (그 다음 문단 최대 3개 점수 합)
  문서 적합도    = 문서 전체(제목·소제목·본문)에서 일치한 개념 비율
  결과 포함 조건 = 문서 적합도 ≥ 0.5 (일반어만 일치하는 문서는 제외) 그리고 문서 점수 ≥ 1.0
  기본 정렬      = 문서 점수 내림차순 → 최종 수정일 최신 → 문서 ID
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date

from core.access_control import AccessController, User
from core.indexer import Indexer
from core.logging_utils import get_logger, log_event
from core.models import CATEGORIES, Chunk, Document
from core.text_utils import Concept, QueryAnalysis, SearchDictionary, analyze_query, normalize_text

MIN_DOC_COVERAGE = 0.5
MIN_DOC_SCORE = 1.0
DEFAULT_TOP_K = 5
MAX_TOP_K = 20
TITLE_W, HEADING_W, BODY_CAP, PHRASE_BONUS = 5.0, 3.0, 3, 1.5
SCOPES = ("all", "name", "body")
SORTS = ("relevance", "modified", "name", "type", "path")

_log = get_logger()


def location_key(doc: Document) -> str:
    """위치 필터 키: 공유폴더는 공유별(`shared_folder:표시이름`), 나머지는 저장소 키."""
    return f"shared_folder:{doc.share}" if doc.source_key == "shared_folder" and doc.share else doc.source_key


@dataclass(frozen=True)
class Passage:
    chunk_seq: int
    heading: str
    text: str
    score: float
    flagged: bool = False
    flag_reason: str = ""
    matched_terms: tuple[str, ...] = ()
    loc: str = ""  # 원문 위치 (p.2 / 시트·셀 / 슬라이드 / 줄)


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
    location: str  # 공유폴더: 원본 UNC 경로 / 그 외: 가상 URL
    location_detail: str
    content_hash: str
    score: float
    coverage: float
    passages: tuple[Passage, ...]
    file_type: str = "md"
    file_name: str = ""
    share: str = ""
    hit_count: int = 0  # 일치한 문단(위치) 수
    name_match: bool = False  # 파일명/제목에서 일치
    index_level: str = "full"  # full | metadata(본문 미색인)
    stale: bool = False  # 색인 이후 원본이 변경됨 → 색인 갱신 필요


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
    metadata_only_count: int = 0  # (권한·필터 적용 후) 본문이 색인되지 않은 문서 수
    volatile: bool = False  # 표시 직전 재검증에서 일부 후보가 거부됨 → 원본 상태가 바뀌면 달라질 수 있어 캐시하지 않는다


def _to_iso(d: date | str | None) -> str | None:
    if d is None or d == "":
        return None
    return d.isoformat() if isinstance(d, date) else str(d)


class SearchEngine:
    def __init__(self, indexer: Indexer, access: AccessController, dictionary: SearchDictionary):
        self.indexer = indexer
        self.access = access
        self.dictionary = dictionary
        self._cache: dict[tuple, tuple[int, SearchResponse]] = {}
        # 색인에 저장되는 정규화 텍스트를 이 엔진의 사전과 항상 일치시킨다 (사전이 바뀌었으면 자동으로 다시 계산)
        indexer.ensure_normalization(dictionary.signature(), lambda t: normalize_text(t, dictionary))

    # -- 캐시 ----------------------------------------------------------------
    def invalidate_cache(self) -> None:
        self._cache.clear()

    def _revalidate(self, user: User | None, response: SearchResponse) -> bool:
        """캐시된 결과의 모든 문서가 지금도 존재·열람 가능·동일 내용인지 재검증."""
        for r in response.results:
            doc = self.indexer.get_document(r.doc_id)
            if doc is None or not self.access.verify(user, doc):  # 캐시 적중이어도 지금 접근 가능한지 재확인
                return False
            if self.indexer.content_hash_of(r.doc_id) != r.content_hash:
                return False
            if self.access.is_stale(doc) != r.stale:
                return False
        return True

    # -- 검색 ----------------------------------------------------------------
    def search(self, user: User | None, query: str, categories: list[str] | None = None,
               sources: list[str] | None = None, top_k: int = DEFAULT_TOP_K, *,
               file_types: list[str] | None = None, locations: list[str] | None = None,
               modified_from: date | str | None = None, modified_to: date | str | None = None,
               scope: str = "all", sort: str = "relevance", descending: bool | None = None) -> SearchResponse:
        top_k = max(1, min(MAX_TOP_K, top_k))
        scope = scope if scope in SCOPES else "all"
        sort = sort if sort in SORTS else "relevance"
        if descending is None:
            descending = sort in ("relevance", "modified")
        date_from, date_to = _to_iso(modified_from), _to_iso(modified_to)
        generation = self.indexer.get_generation()
        unavailable = [s["source_label"] for s in self.indexer.source_statuses() if s["status"] != "ok"]

        if user is None or self.access.get_user(user.user_id) is None:
            return SearchResponse(query, "denied", "확인되지 않은 사용자입니다. 사용자를 선택해 주세요.",
                                  generation=generation)
        if not query or not query.strip():
            return SearchResponse(query or "", "empty_query", "검색어를 입력해 주세요.", generation=generation)

        cache_key = (user.user_id, normalize_text(query.strip(), self.dictionary),
                     tuple(sorted(categories or [])), tuple(sorted(sources or [])), top_k,
                     tuple(sorted(file_types or [])), tuple(sorted(locations or [])), date_from, date_to,
                     scope, sort, descending)
        cached = self._cache.get(cache_key)
        if cached:
            if cached[0] == generation and self._revalidate(user, cached[1]):
                hit = cached[1]
                return SearchResponse(**{**hit.__dict__, "from_cache": True})
            del self._cache[cache_key]  # 색인이 바뀌었거나 재검증 실패 → 폐기 후 재계산

        response = self._search_uncached(user, query, categories, sources, top_k, unavailable, generation,
                                         file_types, locations, date_from, date_to, scope, sort, descending)
        if not response.volatile:  # 일부 후보가 일시적으로 거부된 응답(오프라인·잠금 등)은 복구 후에도 남지 않도록 캐시하지 않는다
            self._cache[cache_key] = (generation, response)
        # 로그: 검색어/본문은 기록하지 않는다 (길이와 건수만)
        log_event(_log, "search", user=user.user_id, query_len=len(query), status=response.status,
                  results=len(response.results), scope=scope, cache=False)
        return response

    @staticmethod
    def _apply_filters(docs: list[Document], categories, sources, file_types, locations, date_from,
                       date_to) -> list[Document]:
        if categories:
            docs = [d for d in docs if d.category in categories]
        if sources:
            docs = [d for d in docs if d.source_key in sources]
        if file_types:
            docs = [d for d in docs if d.file_type in file_types]
        if locations:
            docs = [d for d in docs if location_key(d) in locations]
        if date_from:
            docs = [d for d in docs if d.modified_at >= date_from]
        if date_to:
            docs = [d for d in docs if d.modified_at <= date_to]
        return docs

    def _search_uncached(self, user, query, categories, sources, top_k, unavailable, generation, file_types,
                         locations, date_from, date_to, scope, sort, descending) -> SearchResponse:
        statuses = self.indexer.source_statuses()
        if not any(s["status"] == "ok" for s in statuses):
            msg = ("검색 가능한 저장소가 없습니다. 저장소 연결 상태를 확인한 뒤 '색인 갱신'을 실행해 주세요."
                   if statuses else "연결된 저장소가 없습니다. '색인 갱신'을 먼저 실행해 주세요.")
            return SearchResponse(query, "no_sources", msg, unavailable_sources=unavailable, generation=generation)
        docs = self.indexer.list_documents(searchable_only=True)
        # 1) 권한 필터 (점수 계산 이전)
        docs = self.access.filter_documents(user, docs)
        # 2) 사용자 필터
        docs = self._apply_filters(docs, categories, sources, file_types, locations, date_from, date_to)

        analysis = analyze_query(query, self.dictionary)
        if not analysis.concepts:
            return SearchResponse(query, "no_results", "검색어에서 의미 있는 단어를 찾지 못했습니다. "
                                  "업무 용어를 포함해 다시 질문해 주세요.", analysis=analysis,
                                  unavailable_sources=unavailable, generation=generation)

        meta_only = sum(1 for d in docs if d.index_level == "metadata")
        # 후보 추출: 질의 용어가 하나도 없는 조각은 점수에 기여하지 않으므로 SQL 로 미리 걸러낸다 (결과는 동일)
        name_norms = self.indexer.name_norms() if scope in ("all", "name") else {}
        cand: dict[str, list[Chunk]] = {}
        if scope in ("all", "body"):
            cand = self.indexer.candidate_chunks(sorted({t for c in analysis.concepts for t, _ in c.variants}))
        hashes = self.indexer.content_hashes()
        scored = [r for r in (self._score_document(d, analysis, scope, name_norms.get(d.doc_id), cand.get(d.doc_id, []),
                                                   hashes.get(d.doc_id, "")) for d in docs) if r]
        scored = self._sort(scored, sort, descending)
        total = len(scored)
        # 표시 직전 엄격 재검증: 삭제·권한 회수·공유 불가인 문서는 건너뛰고 다음 순위로 채운다
        final: list[SearchResult] = []
        rejected = 0
        for r in scored:
            if len(final) >= top_k:
                break
            doc = self.indexer.get_document(r.doc_id)
            if doc is None or not self.access.verify(user, doc):
                rejected += 1
                continue
            final.append(replace(r, stale=True) if self.access.is_stale(doc) else r)
        if not final:
            return SearchResponse(query, "no_results", "질문과 관련된 문서를 찾지 못했습니다.", analysis=analysis,
                                  unavailable_sources=unavailable, generation=generation,
                                  metadata_only_count=meta_only, volatile=bool(rejected))
        return SearchResponse(query, "ok", results=final, analysis=analysis, total_matched=total,
                              unavailable_sources=unavailable, generation=generation, metadata_only_count=meta_only,
                              volatile=bool(rejected))

    @staticmethod
    def _sort(results: list[SearchResult], sort: str, descending: bool) -> list[SearchResult]:
        if sort == "relevance":
            base = sorted(results, key=lambda r: (-r.score, _neg_date(r.modified_at), r.doc_id))
            return base if descending else list(reversed(base))
        keys = {
            "modified": lambda r: (r.modified_at, r.doc_id),
            "name": lambda r: ((r.file_name or r.title).casefold(), r.doc_id),
            "type": lambda r: (r.file_type, (r.file_name or r.title).casefold()),
            "path": lambda r: (r.location.casefold(), r.doc_id),
        }
        return sorted(results, key=keys[sort], reverse=descending)

    # -- 점수 계산 -----------------------------------------------------------
    @staticmethod
    def _best_variant(concept: Concept, text: str) -> tuple[float, int, str]:
        """text 안에서 개념의 가장 높은 가중치 용어와 (가중치, 출현횟수, 용어)를 반환.
        변형은 가중치 내림차순(원 질의어 → 동의어)이므로 더 높은 가중치가 이미 일치했으면 나머지는 세지 않는다."""
        best = (0.0, 0, "")
        for term, w in concept.variants:
            if w > best[0]:
                n = text.count(term)
                if n:
                    best = (w, n, term)
        return best

    def _chunk_scores(self, chunks: list[Chunk], analysis: QueryAnalysis, title_hit: set[str]):
        """문단별 (점수, 문단, 일치용어, 일치개념집합). raw 가 0 이면 제외."""
        concepts = analysis.concepts
        core = [c for c in concepts if not c.generic] or concepts
        out = []
        for ch in chunks:
            text = ch.norm_text or normalize_text(ch.text, self.dictionary)
            heading = ch.norm_heading or normalize_text(ch.heading, self.dictionary)
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
            if raw > 0:
                cov = len({c.term for c in core} & hit) / len(core)
                out.append((raw * (0.5 + 0.5 * cov), ch, tuple(dict.fromkeys(terms)), hit))
        return out

    def _score_document(self, doc: Document, analysis: QueryAnalysis, scope: str = "all", name_norm: str | None = None,
                        chunks: list[Chunk] | None = None, content_hash: str | None = None) -> SearchResult | None:
        """chunks/name_norm 을 주면 미리 추출한 후보를 쓰고, 생략하면 문서의 모든 조각을 읽는다(기준 구현, 테스트용)."""
        concepts = analysis.concepts
        core_concepts = [c for c in concepts if not c.generic] or concepts
        use_name = scope in ("all", "name")
        use_body = scope in ("all", "body")
        metadata_level = doc.index_level == "metadata"
        if metadata_level:
            if scope == "body":
                return None  # 본문이 색인되지 않은 문서는 본문 검색 대상이 아니다
            use_body = False

        title_score, title_hit = 0.0, set()
        if use_name:
            # 메타데이터 수준 문서는 폴더 경로도 이름 검색 대상이다 (예: 폴더명으로 찾기)
            name_text = name_norm if name_norm is not None else normalize_text(
                f"{doc.title} {doc.file_name}" + (f" {doc.location}" if metadata_level else ""), self.dictionary)
            for c in concepts:
                w, n, _ = self._best_variant(c, name_text)
                if n:
                    title_score += TITLE_W * w
                    title_hit.add(c.term)

        doc_hit = set(title_hit)
        chunk_scores = []
        if use_body:
            chunk_scores = self._chunk_scores(chunks if chunks is not None else self.indexer.get_chunks(doc.doc_id),
                                              analysis, title_hit)
            for *_, hit in chunk_scores:
                doc_hit |= hit

        doc_cov = len({c.term for c in core_concepts} & doc_hit) / len(core_concepts)
        chunk_scores.sort(key=lambda x: (-x[0], x[1].seq))
        best = chunk_scores[0][0] if chunk_scores else 0.0
        rest = sum(s for s, *_ in chunk_scores[1:4])
        score = title_score + best + 0.25 * rest
        if doc_cov < MIN_DOC_COVERAGE or score < MIN_DOC_SCORE:
            return None
        passages = tuple(
            Passage(ch.seq, ch.heading, ch.text, round(s, 2), ch.flagged, ch.flag_reason, terms, ch.loc)
            for s, ch, terms, _ in chunk_scores[:3]
        )
        return SearchResult(
            doc_id=doc.doc_id, title=doc.title, source_key=doc.source_key, source_system=doc.source_system,
            category=doc.category, version=doc.version, modified_at=doc.modified_at, department=doc.department,
            location=doc.location, location_detail=doc.location_detail,
            content_hash=(content_hash if content_hash is not None else self.indexer.content_hash_of(doc.doc_id)) or "",
            score=round(score, 1), coverage=round(doc_cov, 2), passages=passages, file_type=doc.file_type,
            file_name=doc.file_name, share=doc.share, hit_count=len(chunk_scores), name_match=bool(title_hit),
            index_level=doc.index_level,
        )

    # -- 문서 안 일치 위치 (미리보기의 이전/다음 이동용) ------------------------
    def matching_chunks(self, user: User | None, doc_id: str, query: str) -> list[tuple[int, str, float]]:
        """문서 안에서 질의와 일치하는 문단 [(seq, 위치, 점수)] — 문서 순서. 권한이 없으면 빈 목록."""
        doc = self.indexer.get_document(doc_id)
        if doc is None or not self.access.verify(user, doc) or not query.strip():
            return []
        analysis = analyze_query(query, self.dictionary)
        if not analysis.concepts:
            return []
        scores = self._chunk_scores(self.indexer.get_chunks(doc_id), analysis, set())
        return sorted(((ch.seq, ch.loc, round(s, 2)) for s, ch, *_ in scores))

    # -- 목록/미리보기 (권한 검증 포함) -------------------------------------
    def list_visible_documents(self, user: User | None, categories: list[str] | None = None,
                               sources: list[str] | None = None, *, file_types: list[str] | None = None,
                               locations: list[str] | None = None, modified_from: date | str | None = None,
                               modified_to: date | str | None = None) -> list[Document]:
        docs = self.access.filter_documents(user, self.indexer.list_documents(searchable_only=True))
        return self._apply_filters(docs, categories, sources, file_types, locations, _to_iso(modified_from),
                                   _to_iso(modified_to))

    def open_document(self, user: User | None, doc_id: str) -> tuple[Document, list[Chunk]] | None:
        """원문 미리보기. 문서가 없거나 권한이 없거나 저장소가 검색 불가 상태면 None (사유를 구분하지 않는다)."""
        doc = self.indexer.get_document(doc_id)
        if doc is None or not self.access.verify(user, doc):
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


__all__ = ["SearchEngine", "SearchResponse", "SearchResult", "Passage", "CATEGORIES", "highlight_terms",
           "location_key", "DEFAULT_TOP_K", "MAX_TOP_K", "SCOPES", "SORTS"]
