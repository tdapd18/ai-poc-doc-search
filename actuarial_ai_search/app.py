"""계리 업무자료 AI 통합검색 Tool (교육용 PoC) — Streamlit 3단 화면.

실행: streamlit run app.py
- 모든 자료는 data/ 의 가상 더미데이터이며 실제 사내 시스템·외부 API 에 연결하지 않는다.
- 화면의 '가상 사용자 전환'은 실제 회사 인증이 아니다.
"""
from __future__ import annotations

import html

import streamlit as st

from core.answer_generator import AnswerGenerator
from core.config import load_settings
from core.history import HIDDEN_NOTICE, HistoryEntry, revalidate_history
from core.llm_client import MockLLMClient, build_client
from core.models import CATEGORIES
from core.presentation import SOURCE_KIND, badge_html, safe_highlight_html
from core.services import build_services

st.set_page_config(page_title="계리 업무자료 AI 통합검색", page_icon="🔎", layout="wide")

SUGGESTIONS = [
    "RAFM 모델 실행 오류가 나면 어떻게 대응하나요?",
    "GoC 단위 변동 분석은 어떻게 하나요?",
    "월말 결산 일정과 마감 시한은?",
    "계리적 가정을 변경할 때 승인 절차는?",
    "모델 에러가 났을 때 확인할 순서",
]

st.markdown(
    """
<style>
html, body, [class*="st-"] { font-size: 15px; }
.block-container { padding-top: 3.2rem; max-width: 1700px; }
h1 { color:#1F3A5F; font-size: 1.7rem !important; margin-bottom: .2rem; }
h3 { color:#1F3A5F; font-size: 1.05rem !important; border-bottom: 2px solid #1F3A5F; padding-bottom:.3rem; }
.badge { display:inline-block; padding:2px 9px; border-radius:10px; font-size:12px; font-weight:600; margin-right:6px; }
.badge-sf { background:#E3EAF4; color:#1F3A5F; } .badge-gw { background:#E6F2EE; color:#17624A; }
.badge-bs { background:#F1E9F6; color:#5B2E7A; } .badge-cat { background:#EEF0F3; color:#46505E; }
.badge-warn { background:#FDECEA; color:#A12622; } .badge-ok { background:#E6F2EE; color:#17624A; }
.meta { color:#5A6573; font-size:13px; margin:.15rem 0 .4rem; }
.passage { background:#F6F8FB; border-left:4px solid #1F3A5F; padding:.6rem .8rem; border-radius:4px;
           margin:.4rem 0; line-height:1.65; font-size:14.5px; }
.passage.sel { background:#FFF9E6; border-left-color:#C9A227; }
.passage.flag { background:#FDF3F2; border-left-color:#A12622; }
mark { background:#FFE58F; padding:0 2px; }
.notice { background:#EEF3FA; border:1px solid #C9D6EA; color:#1F3A5F; padding:.5rem .8rem; border-radius:6px; font-size:13.5px; }
.warnbox { background:#FFF6E5; border:1px solid #F0D49A; color:#7A4E00; padding:.5rem .8rem; border-radius:6px; font-size:13.5px; }
.loc { font-family: Consolas, monospace; font-size:12.5px; background:#F3F5F8; padding:3px 6px; border-radius:4px; word-break:break-all; }
div[data-testid="stButton"] button { border-radius:6px; }
</style>
""",
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- 서비스/상태
@st.cache_resource
def get_services():
    settings = load_settings()
    svc = build_services(settings.data_dir, settings.db_path, llm_provider=settings.llm_provider)
    if not svc.indexer.source_statuses():  # 최초 실행 시 1회 자동 색인
        svc.sync.sync()
    return svc, settings


svc, settings = get_services()
ss = st.session_state
ss.setdefault("user_id", svc.access.users()[0].user_id if svc.access.users() else None)
ss.setdefault("history", [])
ss.setdefault("last", None)
ss.setdefault("selected", None)  # (doc_id, chunk_seq | None)
ss.setdefault("sync_report", None)
ss.setdefault("f_categories", list(CATEGORIES))
ss.setdefault("f_sources", [c.source_key for c in svc.connectors])
ss.setdefault("mode_ai", False)
ss.setdefault("use_mock", settings.llm_provider == "mock")
ss.setdefault("query_text", "")


def current_user():
    return svc.access.get_user(ss.user_id)


def answer_generator() -> AnswerGenerator:
    llm = MockLLMClient() if ss.use_mock else build_client(settings.llm_provider)
    return AnswerGenerator(svc.indexer, svc.access, llm)


def _filters():
    cats = ss.f_categories if 0 < len(ss.f_categories) < len(CATEGORIES) else None
    all_src = [c.source_key for c in svc.connectors]
    srcs = ss.f_sources if 0 < len(ss.f_sources) < len(all_src) else None
    return cats, srcs


# --------------------------------------------------------------------------- 콜백
def run_search(query: str, record: bool = True, cats=None, srcs=None, mode: str | None = None) -> None:
    user = current_user()
    if cats is None and srcs is None:
        cats, srcs = _filters()
    mode = mode or ("ai" if ss.mode_ai else "local")
    resp = svc.engine.search(user, query, cats, srcs, settings.top_k)
    ans = answer_generator().answer(user, query, resp, mode)
    ss.last = {"user_id": ss.user_id, "query": query, "mode": mode, "cats": cats, "srcs": srcs,
               "resp": resp, "ans": ans, "generation": resp.generation}
    if resp.status == "ok" and ans.citations:
        ss.selected = (ans.citations[0].doc_id, ans.citations[0].chunk_seq)
    elif resp.status != "ok":
        ss.selected = None
    if record and resp.status in ("ok", "no_results") and user:
        if ans.mode == "ai" and ans.answer_text:
            text = ans.answer_text
        elif resp.status == "ok":
            text = f"관련 문서 {len(resp.results)}건: " + ", ".join(r.title for r in resp.results)
        else:
            text = "관련 문서를 찾지 못했습니다."
        seen, sources = set(), []
        for c in ans.citations or []:
            if c.doc_id not in seen:
                seen.add(c.doc_id)
                sources.append((c.doc_id, c.title, c.content_hash))
        if not sources:
            sources = [(r.doc_id, r.title, r.content_hash) for r in resp.results]
        ss.history.insert(0, HistoryEntry(user.user_id, query, ans.mode, text, sources))
        del ss.history[30:]


def on_submit() -> None:
    run_search(ss.query_text)


def on_suggest(q: str) -> None:
    ss.query_text = q
    run_search(q)


def on_user_change() -> None:
    ss.last = None
    ss.selected = None


def on_select(doc_id: str, seq: int | None = None) -> None:
    ss.selected = (doc_id, seq)


def on_sync() -> None:
    ss.sync_report = svc.sync.sync()


# --------------------------------------------------------------------------- 레이아웃
user = current_user()
left, center, right = st.columns([1.05, 2.1, 1.45], gap="large")

# ================= 왼쪽: 자료 관리 및 검색 범위 =================
with left:
    st.markdown("### 자료 관리 · 검색 범위")
    st.selectbox(
        "가상 사용자 선택", options=[u.user_id for u in svc.access.users()],
        format_func=lambda uid: svc.access.get_user(uid).name, key="user_id", on_change=on_user_change,
    )
    st.markdown(
        '<div class="warnbox">⚠ 교육용 <b>가상 사용자</b> 전환입니다. 실제 회사 인증(SSO/AD)이 아니며, '
        "운영 시에는 사내 인증·원본 시스템 ACL 연동이 필요합니다.</div>", unsafe_allow_html=True)

    visible_all = svc.engine.list_visible_documents(user)
    st.metric("접근 가능한 통합 문서 수", len(visible_all))

    st.markdown("**연결된 저장소**")
    if not svc.connectors:
        st.warning("연결된 저장소가 없습니다.")
    statuses = {s["source_key"]: s for s in svc.indexer.source_statuses()}
    for conn in svc.connectors:
        stt = statuses.get(conn.source_key)
        n = sum(1 for d in visible_all if d.source_key == conn.source_key)
        kind = SOURCE_KIND.get(conn.source_key, "cat")
        if stt is None:
            state = badge_html("미동기화", "warn")
        elif stt["status"] == "ok":
            state = badge_html("정상", "ok")
        else:
            state = badge_html("연결 오류·검색 제외", "warn")
        st.markdown(f"{badge_html(conn.source_label, kind)} {state} 문서 {n if stt and stt['status']=='ok' else '-'}건",
                    unsafe_allow_html=True)

    st.multiselect("문서 분류 필터", CATEGORIES, key="f_categories")
    st.multiselect("저장소 필터", [c.source_key for c in svc.connectors], key="f_sources",
                   format_func=lambda k: next(c.source_label for c in svc.connectors if c.source_key == k))

    st.button("🔄 색인 갱신", on_click=on_sync, help="저장소의 신규·수정·삭제·권한 변경을 색인에 반영합니다")
    rep = ss.sync_report
    if rep is not None:
        if rep.failed_sources:
            st.warning("일부 저장소 동기화 실패: " + ", ".join(s.source_label for s in rep.failed_sources))
        elif rep.changed:
            st.success("색인을 갱신했습니다. 변경 사항이 반영되었습니다.")
        else:
            st.info("변경된 문서가 없습니다.")
        with st.expander("갱신 상세"):
            for line in rep.summary_lines():
                st.text(line)

    st.markdown("**문서 목록**")
    cats, srcs = _filters()
    docs = svc.engine.list_visible_documents(user, cats, srcs)
    if not docs:
        st.caption("표시할 문서가 없습니다.")
    for d in docs:
        st.button(d.title, key=f"doc_{d.doc_id}", on_click=on_select, args=(d.doc_id, None))
        st.markdown(f'<div class="meta">{badge_html(d.source_system, SOURCE_KIND.get(d.source_key, "cat"))}'
                    f'{badge_html(d.category, "cat")} v{html.escape(d.version)} · 수정 {d.modified_at}</div>',
                    unsafe_allow_html=True)

# ================= 가운데: AI 통합 검색 =================
with center:
    st.title("🔎 계리 업무자료 AI 통합검색")
    st.caption("공유폴더 · 그룹웨어 · 업무시스템의 가상 자료를 한 번에 검색하고, 근거 문서와 원본 위치를 확인합니다. "
               "(교육용 PoC · 가상 더미데이터)")

    with st.form("search_form"):
        st.text_input("질문", key="query_text", placeholder="예) RAFM 모델 실행 오류가 나면 어떻게 대응하나요?")
        c1, c2 = st.columns([1, 3])
        c1.form_submit_button("검색", on_click=on_submit)
    st.caption("추천 질문")
    scols = st.columns(len(SUGGESTIONS))
    for i, q in enumerate(SUGGESTIONS):
        scols[i].button(q, key=f"sug_{i}", on_click=on_suggest, args=(q,))

    with st.expander("답변 모드 설정"):
        st.toggle("AI 답변 모드 (선택 기능)", key="mode_ai",
                  help="끄면 로컬 검색 모드(기본): 외부 AI 없이 원문 문단만 표시합니다.")
        st.checkbox("Mock LLM 사용 (구조 테스트용 · 실제 생성형 AI 아님)", key="use_mock")
        if ss.mode_ai and not ss.use_mock and settings.llm_provider != "mock":
            st.info("실제 LLM은 연결되지 않았습니다(LLM_PROVIDER=none). 질문하면 로컬 검색 모드 결과로 대체됩니다.")
        st.caption(f"실제 생성형 AI 연결: **미연결** · LLM_PROVIDER={settings.llm_provider}")

    # --- 결과 영역 -------------------------------------------------------
    last = ss.last
    if last and last["user_id"] != ss.user_id:
        last = ss.last = None
    if last and last["generation"] != svc.indexer.get_generation():  # 색인/권한 변경 → 재검증(재검색)
        q = last["query"]
        run_search(q, record=False, cats=last["cats"], srcs=last["srcs"], mode=last["mode"])
        last = ss.last
        st.info("색인 또는 접근권한이 갱신되어 검색 결과를 다시 계산했습니다.")

    if last:
        resp, ans = last["resp"], last["ans"]
        if resp.unavailable_sources:
            st.warning("⚠ 일부 저장소를 검색하지 못했습니다: " + ", ".join(resp.unavailable_sources)
                       + " — 나머지 저장소의 결과만 표시됩니다.")
        if resp.status == "empty_query":
            st.warning(resp.message)
        elif resp.status in ("no_sources", "denied"):
            st.error(resp.message)
        elif resp.status == "no_results":
            st.info("관련 문서를 찾지 못했습니다. 다른 표현이나 업무 용어(예: RAFM, GoC, 결산)로 다시 질문하거나 "
                    "분류·저장소 필터를 확인해 보세요.")
        else:
            by_source: dict[str, int] = {}
            for r in resp.results:
                by_source[r.source_system] = by_source.get(r.source_system, 0) + 1
            chips = " ".join(badge_html(f"{k} {v}건", SOURCE_KIND.get(
                next(r.source_key for r in resp.results if r.source_system == k), "cat")) for k, v in by_source.items())
            terms = tuple(t for c in resp.analysis.concepts for t, _ in c.variants) if resp.analysis else ()

            with st.container(border=True):
                if ans.mode == "ai" and ans.status in ("ok", "insufficient"):
                    st.markdown(f"**AI 답변 모드** · {html.escape(ans.llm_label)}")
                    if ans.is_mock:
                        st.markdown('<div class="notice">Mock 구조 테스트 응답입니다. 실제 생성형 AI가 만든 답변이 아니며 '
                                    "근거 문단 첫 문장을 규칙으로 이어 붙인 것입니다.</div>", unsafe_allow_html=True)
                    st.write(ans.answer_text)
                else:
                    if ans.fallback_reason:
                        st.warning(ans.fallback_reason)
                    st.markdown('<div class="notice">' + html.escape(ans.notice) + "</div>", unsafe_allow_html=True)
                st.markdown(f"관련 문서 {len(resp.results)}건 " + chips, unsafe_allow_html=True)

                for c in ans.citations:
                    flag = " flag" if c.flagged else ""
                    sel = " sel" if ss.selected == (c.doc_id, c.chunk_seq) else ""
                    warn = (f'<br><span class="badge badge-warn">⚠ 지시문 의심 문장 포함 ({html.escape(c.flag_reason)})</span> '
                            "이 문장은 데이터로만 표시되며 실행되지 않고, AI에도 전달되지 않습니다.") if c.flagged else ""
                    st.markdown(
                        f'<div class="passage{flag}{sel}"><b>[{c.number}]</b> '
                        f'<span class="meta">{html.escape(c.title)} · v{html.escape(c.version)} · '
                        f'{html.escape(c.source_system)}</span><br>'
                        f'{safe_highlight_html(c.text[:420] + ("…" if len(c.text) > 420 else ""), terms)}{warn}</div>',
                        unsafe_allow_html=True)
                    st.button(f"[{c.number}] 근거 문서 보기", key=f"cite_{c.number}_{c.doc_id}_{c.chunk_seq}",
                              on_click=on_select, args=(c.doc_id, c.chunk_seq))

            st.markdown("##### 관련 근거 문서 (관련성 순)")
            for r in resp.results:
                with st.container(border=True):
                    st.markdown(
                        f'{badge_html(r.source_system, SOURCE_KIND.get(r.source_key, "cat"))}'
                        f'{badge_html(r.category, "cat")} <b>{html.escape(r.title)}</b>'
                        f'<div class="meta">v{html.escape(r.version)} · 수정 {r.modified_at} · {html.escape(r.department)}'
                        f" · 관련도 점수 {r.score}</div>"
                        f'<div class="meta">원본 위치: <span class="loc">{html.escape(r.location)}</span></div>',
                        unsafe_allow_html=True)
                    st.button("원문 확인", key=f"open_{r.doc_id}", on_click=on_select,
                              args=(r.doc_id, r.passages[0].chunk_seq if r.passages else None))
            if resp.total_matched > len(resp.results):
                st.caption(f"관련 문서 {resp.total_matched}건 중 상위 {len(resp.results)}건을 표시했습니다.")
            with st.expander("검색어 해석 보기"):
                st.write("정규화된 질문: ", resp.analysis.normalized)
                for c in resp.analysis.concepts:
                    syn = [t for t, w in c.variants if t != c.term]
                    st.write(f"- **{c.term}**" + (" (일반어)" if c.generic else "")
                             + (f" ≈ {', '.join(syn)}" if syn else ""))
    else:
        st.markdown('<div class="notice">질문을 입력하거나 추천 질문을 선택하세요. 현재 선택한 가상 사용자가 '
                    "접근할 수 있는 문서만 검색됩니다.</div>", unsafe_allow_html=True)

    # --- 이전 질문/답변 (매 렌더링마다 권한·내용 재검증) ---------------------
    st.markdown("##### 이전 질문 및 답변")
    shown = revalidate_history(ss.history, user, svc.indexer, svc.access)
    if not shown:
        st.caption("이전 질문이 없습니다.")
    for de in shown[:8]:
        e = de.entry
        with st.expander(f"{e.created_at} · {e.query}"):
            if de.hidden:
                st.warning(HIDDEN_NOTICE)
            else:
                st.markdown(f"*{'AI 답변 모드' if e.mode == 'ai' else '로컬 검색 모드'}*")
                st.write(e.answer_text)
            st.button("다시 검색", key=f"redo_{e.entry_id}", on_click=on_suggest, args=(e.query,))

# ================= 오른쪽: 근거 문서 확인 =================
with right:
    st.markdown("### 근거 문서 확인")
    sel = ss.selected
    opened = svc.engine.open_document(user, sel[0]) if sel else None
    if not sel:
        st.markdown('<div class="notice">검색 결과의 <b>근거 문서 보기</b> 또는 <b>원문 확인</b> 버튼, 혹은 왼쪽 문서 목록을 '
                    "선택하면 여기에 원문이 표시됩니다.</div>", unsafe_allow_html=True)
    elif opened is None:
        st.warning("이 문서를 열 수 없습니다. 문서가 삭제되었거나 열람 권한이 없습니다.")
    else:
        doc, chunks = opened
        st.markdown(f"#### {html.escape(doc.title)}")
        st.markdown(badge_html(doc.source_system, SOURCE_KIND.get(doc.source_key, "cat")) + badge_html(doc.category, "cat"),
                    unsafe_allow_html=True)
        st.markdown(
            f"- **문서 ID**: `{doc.doc_id}`\n- **저장된 시스템**: {doc.source_system}\n- **문서 버전**: {doc.version}\n"
            f"- **작성일 / 최종 수정일**: {doc.created_at} / {doc.modified_at}\n- **담당 부서**: {doc.department}")
        st.markdown("**원본 위치**")
        st.markdown(f'<span class="loc">{html.escape(doc.location)}</span>', unsafe_allow_html=True)
        if doc.location_detail:
            st.caption(doc.location_detail)
        st.caption("가상 원본 링크입니다(예약 도메인 .invalid). 실제 시스템에는 연결되지 않습니다.")

        terms: tuple[str, ...] = ()
        if ss.last and ss.last["resp"].analysis:
            terms = tuple(t for c in ss.last["resp"].analysis.concepts for t, _ in c.variants)
        st.markdown("**원문** (선택한 근거 문단은 노란색으로 표시)")
        for ch in chunks:
            cls = "passage" + (" sel" if sel[1] == ch.seq else "") + (" flag" if ch.flagged else "")
            head = f"<b>{html.escape(ch.heading)}</b><br>" if ch.heading != doc.title else ""
            warn = (f'<br><span class="badge badge-warn">⚠ 지시문 의심: {html.escape(ch.flag_reason)}</span> '
                    "문서 속 문장은 실행되지 않습니다.") if ch.flagged else ""
            st.markdown(f'<div class="{cls}">{head}{safe_highlight_html(ch.text, terms)}{warn}</div>',
                        unsafe_allow_html=True)
        if doc.attachments:
            st.caption("첨부파일(목록만 수집): " + ", ".join(doc.attachments))
