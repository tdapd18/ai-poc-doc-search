"""PoC 3: local literal retrieval, cited evidence, deterministic abstention."""
import re
from pathlib import Path

MAX_DOC_BYTES = 1024 * 1024
STOPWORDS = {'방법', '관련', '대한', '어떤', '있는', '알려줘', '알려주세요', '어떻게', '할까요', '사항'}
SYNONYMS = {'체크할': '점검', '체크': '점검', '체크리스트': '점검', '항목': '점검', '증감': '변동'}
DOMAIN = {'goc', 'rafm', 'ifrs17'}


def chunks_from_text(name: str, raw: str) -> list[dict]:
    title, version, category, owner = '', '', '', ''
    current, content, result = '', [], []
    def flush():
        if current and content:
            body = ' '.join(content).strip()
            if body:
                result.append({'title': title, 'version': version, 'category': category,
                               'owner': owner, 'file': name, 'section': current, 'text': body,
                               'source': name + '#'+ current})
    for line in raw.splitlines():
        t = line.strip()
        if t.startswith('# ') and not title:
            title = t[2:].strip()
        elif t.startswith('- 버전:'):
            version = t.split(':',1)[1].strip()
        elif t.startswith('- 분류:'):
            category = t.split(':',1)[1].strip()
        elif t.startswith('- 담당자:'):
            owner = t.split(':',1)[1].strip()
        elif t.startswith('## '):
            flush()
            current, content = t[3:].strip(), []
        elif current and t and not t.startswith('#'):
            content.append(t)
    flush()
    if not title or not version or not result:
        raise ValueError(f'{name}: H1 제목, 버전, ## 절과 본문이 모두 필요합니다.')
    return result


def load_docs(folder: Path) -> list[dict]:
    files = sorted(folder.glob('*.md'))
    if len(files) < 3:
        raise ValueError('검색 폴더에 가상 Markdown 문서가 3개 이상 있어야 합니다.')
    docs = []
    for path in files:
        if path.stat().st_size > MAX_DOC_BYTES:
            raise ValueError(path.name + ': 파일이 1MB를 초과했습니다.')
        try:
            docs.extend(chunks_from_text(path.name, path.read_text(encoding='utf-8-sig')))
        except UnicodeError as exc:
            raise ValueError(path.name + ': UTF-8 인코딩 문서가 아닙니다.') from exc
    return docs


def tokens(question: str) -> set[str]:
    raw = re.findall(r'(?i)e\d{3}|[가-힣]{2,}|[a-zA-Z]+\d*', question.lower())
    words = set()
    for item in raw:
        term = item.strip().lower()
        for k, v in SYNONYMS.items():
            if term.startswith(k):
                term = v
                break
        if term not in STOPWORDS and len(term) >= 2:
            words.add(term)
    return words


def search(chunks: list[dict], question: str, limit: int = 3) -> list[dict]:
    q = tokens(question)
    if not q:
        return []
    matches = []
    for chunk in chunks:
        text = (chunk['section'] + ' ' + chunk['text']).casefold()
        title = chunk['title'].casefold()
        hits = {term for term in q if term in text or term in title}
        strong = {term for term in hits if re.fullmatch(r'e\d{3}', term) or term in DOMAIN}
        if len(hits) < 2 and not strong:
            continue
        score = sum(8 if re.fullmatch(r'e\d{3}', term) else (4 if term in DOMAIN else 2) for term in hits)
        score += sum(2 for term in hits if term in title)
        matches.append({**chunk, 'score': score, 'matched': ', '.join(sorted(hits))})
    matches.sort(key=lambda c: (-c['score'], c['file'], c['section']))
    return matches[:limit]
