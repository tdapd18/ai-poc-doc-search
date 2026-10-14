"""한국어 업무 질의 처리: 용어 정규화, 조사/어미 제거, 업무 동의어 확장.

형태소 분석기를 쓰지 않는 단순 규칙 기반이다 (외부 라이브러리/인터넷 불필요).

처리 순서
1. 소문자화, 별칭 정규화  (예: "IFRS 17" → "ifrs17", "보험계약집단" → "goc")
2. 토큰 추출 : 영문/숫자 덩어리, 한글 덩어리
3. 한글 토큰의 끝 조사/어미 제거 (남는 글자 수가 2 이상일 때만)  예: "오류가" → "오류", "발생하면" → "발생"
4. 불용어 제거, 한 글자 토큰 제거
5. 각 토큰 = 하나의 "개념(concept)". 같은 동의어 그룹의 용어는 하나의 개념으로 묶인다.
   - 원 질의어 가중치 1.0, 동의어 0.6, 일반어(generic_terms) 0.3 (일반어는 적합도 판정에서 제외)
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_TOKEN_RE = re.compile(r"[0-9A-Za-z]+|[가-힣]+")
# 긴 접미사부터 검사한다.
_SUFFIXES = sorted(
    ["에서는", "으로는", "이라고", "입니다", "인가요", "일까요", "할까요", "하나요", "되나요", "하면", "하는", "해야",
     "했을", "했나", "됩니다", "되면", "되는", "에서", "으로", "에는", "에도", "부터", "까지", "에게", "한테",
     "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "만", "할", "한", "해", "하고"],
    key=len, reverse=True,
)

W_ORIGINAL, W_SYNONYM, W_GENERIC = 1.0, 0.6, 0.3


@dataclass(frozen=True)
class Concept:
    term: str  # 원 질의어 (정규화 후)
    variants: tuple[tuple[str, float], ...]  # (용어, 가중치) — 원 질의어 포함
    generic: bool = False


@dataclass
class QueryAnalysis:
    raw: str
    normalized: str
    concepts: list[Concept] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)  # 불용어 제거 후 원 질의 토큰 순서


class SearchDictionary:
    def __init__(self, data: dict):
        self.aliases: dict[str, str] = {k.lower(): v.lower() for k, v in data.get("alias_normalization", {}).items()}
        self.stopwords = {w.lower() for w in data.get("stopwords", [])}
        self.generic = {w.lower() for w in data.get("generic_terms", [])}
        self._group_of: dict[str, tuple[str, ...]] = {}
        for group in data.get("synonym_groups", []):
            g = tuple(dict.fromkeys(t.lower() for t in group))
            for term in g:
                self._group_of[term] = g

    @classmethod
    def from_file(cls, path: Path | str) -> "SearchDictionary":
        try:
            return cls(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return cls({})  # 사전이 없어도 검색은 동작한다 (동의어 확장만 비활성)

    def signature(self) -> str:
        """정규화 규칙(별칭)의 지문. 바뀌면 색인에 저장된 정규화 텍스트를 다시 계산해야 한다."""
        return hashlib.sha1(json.dumps(sorted(self.aliases.items()), ensure_ascii=False).encode("utf-8")).hexdigest()

    def synonyms(self, term: str) -> tuple[str, ...]:
        return self._group_of.get(term, (term,))


def normalize_text(text: str, dictionary: SearchDictionary | None = None) -> str:
    """검색 대상/질의 공통 정규화: 소문자 + 별칭 치환 + 공백 정리."""
    out = text.lower()
    if dictionary:
        for alias in sorted(dictionary.aliases, key=len, reverse=True):
            if alias in out:
                out = out.replace(alias, dictionary.aliases[alias])
    return re.sub(r"[ \t]+", " ", out)


def _strip_suffix(token: str) -> str:
    if not re.fullmatch(r"[가-힣]+", token):
        return token
    for suf in _SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= 2:
            return token[: -len(suf)]
    return token


def analyze_query(raw: str, dictionary: SearchDictionary) -> QueryAnalysis:
    normalized = normalize_text(raw, dictionary)
    tokens: list[str] = []
    for tok in _TOKEN_RE.findall(normalized):
        tok = _strip_suffix(tok)
        if len(tok) < 2 or tok in dictionary.stopwords:
            continue
        tokens.append(tok)

    concepts: list[Concept] = []
    seen_groups: set[tuple[str, ...]] = set()
    for tok in dict.fromkeys(tokens):  # 중복 제거, 순서 유지
        if tok in dictionary.generic:
            concepts.append(Concept(tok, ((tok, W_GENERIC),), generic=True))
            continue
        group = dictionary.synonyms(tok)
        if group in seen_groups:  # 같은 동의어 그룹의 두 번째 용어 → 이미 반영됨
            continue
        seen_groups.add(group)
        variants = [(tok, W_ORIGINAL)] + [(s, W_SYNONYM) for s in group if s != tok]
        concepts.append(Concept(tok, tuple(variants)))
    return QueryAnalysis(raw=raw, normalized=normalized, concepts=concepts, tokens=tokens)
