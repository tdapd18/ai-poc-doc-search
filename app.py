"""계리 업무자료 AI 통합검색 Tool (교육용 PoC) — Streamlit 3단 화면.

실행: streamlit run app.py
- 왼쪽 '검색 범위 및 필터' / 가운데 '검색 결과' / 오른쪽 '관련 원문 미리보기'
- 모든 자료는 data/ 의 가상 더미데이터이며 실제 사내 시스템·외부 API 에 연결하지 않는다.
- 화면의 '가상 사용자 전환'은 실제 회사 인증이 아니다.
"""
from __future__ import annotations

import html
import os
from datetime import date, timedelta

import streamlit as st

from core.answer_generator import AnswerGenerator
from core.config import load_settings
from core.history import HIDDEN_NOTICE, HistoryEntry, revalidate_history
from core.llm_client import MockLLMClient, build_client
from core.models import CATEGORIES, FILE_TYPE_SHORT, FILE_TYPES
from core.presentation import (SOURCE_KIND, TYPE_KIND, badge_html, folder_of, make_snippet, path_html,
                               safe_highlight_html)
from core.search_engine import SCOPES, SORTS, location_key
from core.services import StorageBlockedError, build_real_services, build_services, sync_with_audit
from ui.setup_page import render_setup
from core.shares import ShareError

st.set_page_config(page_title="계리 업무자료 AI 통합검색", page_icon="🔎", layout="wide")

SUGGESTIONS = [
    "RAFM 모델 실행 오류가 나면 어떻게 대응하나요?",
    "GoC 단위 변동 분석은 어떻게 하나요?",
    "월말 결산 일정과 마감 시한은?",
    "CSM 변동률 기준",
    "E101 오류 조치",
]
TYPE_ORDER = ["pdf", "docx", "xlsx", "pptx", "csv", "md", "txt", "doc", "xls", "ppt", "hwp", "post", "record"]
APP_MODE = os.environ.get("APP_MODE", "demo").strip().lower()  # demo(가상 데이터, 기본) | real(실제 Windows 공유폴더)
REAL = APP_MODE == "real"
SORT_LABELS = {"relevance": "관련도", "modified": "수정일", "name": "파일명", "type": "형식", "path": "경로"}
SCOPE_LABELS = {"all": "파일명 + 본문", "name": "파일명만", "body": "본문만"}
DATE_PRESETS = ["전체", "최근 7일", "최근 30일", "최근 90일", "직접 지정"]

st.markdown(
    """
<style>
html, body, [class*="st-"] { font-size: 15px; }
.block-container { padding-top: 3.2rem; max-width: 1760px; }
h1 { color:#1F3A5F; font-size: 1.6rem !important; margin-bottom: .1rem; }
h3 { color:#1F3A5F; font-size: 1.05rem !important; border-bottom: 2px solid #1F3A5F; padding-bottom:.3rem; }
.badge { display:inline-block; padding:1px 9px; border-radius:10px; font-size:12px; font-weight:700; margin-right:5px; white-space:nowrap; }
.badge-sf { background:#E3EAF4; color:#1F3A5F; } .badge-gw { background:#E6F2EE; color:#17624A; }
.badge-bs { background:#F1E9F6; color:#5B2E7A; } .badge-cat { background:#EEF0F3; color:#46505E; }
.badge-warn { background:#FDECEA; color:#A12622; } .badge-ok { background:#E6F2EE; color:#17624A; }
.badge-pdf { background:#FBE4E1; color:#A12622; } .badge-xls { background:#E1F2E6; color:#1B6B35; }
.badge-ppt { background:#FCEBDC; color:#9A4A0B; } .badge-txt { background:#E9ECF1; color:#3C4655; }
.meta { color:#5A6573; font-size:13px; margin:.15rem 0 .35rem; }
.rtitle { font-size:16px; font-weight:700; color:#1F3A5F; }
.path { font-family: Consolas, 'SF Mono', monospace; font-size:12.5px; background:#F3F5F8; color:#2B3646;
        padding:2px 7px; border-radius:4px; word-break:break-all; display:inline-block; }
.hit { background:#F6F8FB; border-left:4px solid #1F3A5F; padding:.4rem .7rem; border-radius:4px; margin:.25rem 0;
       line-height:1.6; font-size:14px; }
.hit .loc { display:inline-block; font-weight:700; color:#1F3A5F; background:#E3EAF4; border-radius:4px; padding:0 7px;
            margin-right:8px; font-size:12.5px; }
.hit.sel { background:#FFF9E6; border-left-color:#C9A227; }
.hit.flag { background:#FDF3F2; border-left-color:#A12622; }
.passage { background:#F6F8FB; border-left:4px solid #1F3A5F; padding:.6rem .8rem; border-radius:4px; margin:.4rem 0;
           line-height:1.65; font-size:14.5px; }
.passage.sel { background:#FFF9E6; border-left-color:#C9A227; }
.passage.flag { background:#FDF3F2; border-left-color:#A12622; }
.passage.dim { opacity:.78; }
.passage .loc { display:block; font-weight:700; color:#1F3A5F; font-size:12.5px; margin-bottom:2px; }
mark { background:#FFE58F; padding:0 2px; border-radius:2px; }
.notice { background:#EEF3FA; border:1px solid #C9D6EA; color:#1F3A5F; padding:.5rem .8rem; border-radius:6px; font-size:13.5px; }
.warnbox { background:#FFF6E5; border:1px solid #F0D49A; color:#7A4E00; padding:.5rem .8rem; border-radius:6px; font-size:13.5px; }
.chip { display:inline-block; background:#EEF0F3; color:#46505E; border-radius:12px; padding:1px 10px; font-size:12.5px; margin:0 5px 4px 0; }
div[data-testid="stButton"] button { border-radius:6px; }
</style>
""",
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- 서비스/상태
@st.cache_resource
def get_services(mode: str):
    settings = load_settings()
    if mode == "real":  # 실제 모드: 자동 색인하지 않는다(초기 설정 화면에서 사용자가 직접 생성)
        return build_real_services(llm_provider=settings.llm_provider), settings
    svc = build_services(settings.data_dir, settings.db_path, llm_provider=settings.llm_provider)
    if not svc.indexer.source_statuses():  # 최초 실행 시 1회 자동 색인
        svc.sync.sync()
    return svc, settings


svc, settings = get_services(APP_MODE)
ss = st.session_state
ss.setdefault("user_id", svc.identity.principal if REAL else (svc.access.users()[0].user_id if svc.access.users() else None))
ss.setdefault("page", "setup" if REAL and not svc.shares.list() else "search")
ss.setdefault("history", [])
ss.setdefault("last", None)
ss.setdefault("selected", None)  # (doc_id, chunk_seq | None)
ss.setdefault("sync_report", None)
ss.setdefault("f_cats", [])
ss.setdefault("f_types", [])
ss.setdefault("f_locs", [])
ss.setdefault("date_preset", "전체")
ss.setdefault("scope", "all")
ss.setdefault("sort", "relevance")
ss.setdefault("sort_desc", True)
ss.setdefault("top_k", settings.top_k)
ss.setdefault("mode_ai", False)
ss.setdefault("use_mock", settings.llm_provider == "mock")
ss.setdefault("query_text", "")
ss.setdefault("only_matches", False)
ss.setdefault("flash", None)


def current_user():
    return svc.access.get_user(ss.user_id)


def answer_generator() -> AnswerGenerator:
    llm = MockLLMClient() if ss.use_mock else build_client(settings.llm_provider)
    return AnswerGenerator(svc.indexer, svc.access, llm)


def reference_date(visible) -> date:
    """'최근 N일' 의 기준일 = 접근 가능한 자료 중 가장 최근 수정일 (가상 자료의 날짜가 고정이라 오늘 날짜를 쓰지 않는다)."""
    dates = [d.modified_at for d in visible]
    return date.fromisoformat(max(dates)) if dates else date.today()


def date_bounds(visible) -> tuple[date | None, date | None]:
    preset = ss.date_preset
    if preset == "전체":
        return None, None
    ref = reference_date(visible)
    if preset == "직접 지정":
        rng = ss.get("date_range")
        if isinstance(rng, (tuple, list)) and len(rng) == 2:
            return rng[0], rng[1]
        return None, None
    days = {"최근 7일": 7, "최근 30일": 30, "최근 90일": 90}[preset]
    return ref - timedelta(days=days), ref


def filter_params(visible) -> dict:
    d_from, d_to = date_bounds(visible)
    return dict(categories=list(ss.f_cats) or None, file_types=list(ss.f_types) or None,
                locations=list(ss.f_locs) or None, modified_from=d_from, modified_to=d_to,
                scope=ss.scope, sort=ss.sort, descending=ss.sort_desc, top_k=int(ss.top_k))


# --------------------------------------------------------------------------- 콜백
def run_search(query: str, record: bool = True, params: dict | None = None, mode: str | None = None) -> None:
    user = current_user()
    visible = svc.engine.list_visible_documents(user)
    params = params or filter_params(visible)
    mode = mode or ("ai" if ss.mode_ai else "local")
    kw = dict(params)
    top_k = kw.pop("top_k")
    resp = svc.engine.search(user, query, kw.pop("categories"), None, top_k, **kw)
    ans = answer_generator().answer(user, query, resp, mode)
    ss.last = {"user_id": ss.user_id, "query": query, "mode": mode, "params": params, "resp": resp, "ans": ans,
               "generation": resp.generation}
    if resp.status == "ok" and resp.results:
        r0 = resp.results[0]
        ss.selected = (r0.doc_id, r0.passages[0].chunk_seq if r0.passages else None)
    elif resp.status != "ok":
        ss.selected = None
    if record and resp.status in ("ok", "no_results") and user:
        if ans.mode == "ai" and ans.answer_text:
            text = ans.answer_text
        elif resp.status == "ok":
            text = (f"관련 문서 {resp.total_matched}건: " if resp.counts_exact else "접근 확인된 문서: ") \
                + ", ".join(r.title for r in resp.results)
        else:
            text = "관련 문서를 찾지 못했습니다."
        sources = [(r.doc_id, r.title, r.content_hash) for r in resp.results]
        ss.history.insert(0, HistoryEntry(user.user_id, query, ans.mode, text, sources))
        del ss.history[30:]


def on_submit() -> None:
    run_search(ss.query_text)


def on_suggest(q: str) -> None:
    ss.query_text = q
    run_search(q)


def on_option_change() -> None:
    """필터·정렬·검색 대상이 바뀌면 직전 검색어로 즉시 다시 검색한다."""
    last = ss.last
    if last and last["resp"].status not in ("empty_query",) and last["query"].strip():
        run_search(last["query"], record=False)


def on_user_change() -> None:
    ss.last = None
    ss.selected = None
    ss.f_cats, ss.f_types, ss.f_locs = [], [], []


def on_reset_filters() -> None:
    ss.f_cats, ss.f_types, ss.f_locs = [], [], []
    ss.date_preset = "전체"
    ss.pop("date_range", None)
    ss.scope, ss.sort, ss.sort_desc = "all", "relevance", True
    on_option_change()


def on_select(doc_id: str, seq: int | None = None) -> None:
    ss.selected = (doc_id, seq)


def on_sync() -> None:
    try:
        ss.sync_report = sync_with_audit(svc) if REAL else svc.sync.sync()
    except StorageBlockedError as exc:
        ss.flash = ("error", str(exc))


def on_register(name: str, unc: str, local_dir: str) -> None:
    try:
        svc.shares.register(name, unc, local_dir)
    except ShareError as exc:
        ss.flash = ("error", str(exc))
        return
    ss.flash = ("success", f"'{name}' 공유폴더를 등록했습니다. 색인을 갱신했습니다.")
    on_sync()


def on_unregister(name: str) -> None:
    svc.shares.unregister(name)
    ss.flash = ("success", f"'{name}' 공유폴더 등록을 해제했습니다. 색인을 갱신했습니다.")
    on_sync()


def on_toggle_share(name: str, key: str) -> None:
    svc.shares.set_enabled(name, bool(ss[key]))
    on_sync()


# --------------------------------------------------------------------------- 표시 보조
def type_badge(ftype: str) -> str:
    return badge_html(FILE_TYPE_SHORT.get(ftype, ftype.upper()), TYPE_KIND.get(ftype, "txt"))


def path_label(source_key: str) -> str:
    return "원본 UNC 경로" if source_key == "shared_folder" else "원본 위치 (가상 URL)"


def query_terms(resp) -> tuple[str, ...]:
    return tuple(t for c in resp.analysis.concepts for t, _ in c.variants) if resp and resp.analysis else ()


def loc_options(visible) -> dict[str, tuple[str, int]]:
    """위치 필터 선택지 {키: (표시명, 문서수)} — 접근 가능한 문서가 있는 위치만 노출한다."""
    out: dict[str, tuple[str, int]] = {}
    for d in visible:
        key = location_key(d)
        label = f"공유폴더 · {d.share}" if d.source_key == "shared_folder" and d.share else d.source_system
        out[key] = (label, out.get(key, (label, 0))[1] + 1)
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------- 레이아웃
if REAL:
    st.radio("화면", ["search", "setup"], format_func=lambda p: "🔎 검색" if p == "search" else "⚙ 초기 설정", key="page",
             horizontal=True, label_visibility="collapsed")
    if ss.page == "setup":
        render_setup(st, svc, ss)
        st.stop()
user = current_user()
visible_all = svc.engine.list_visible_documents(user)
left, center, right = st.columns([1.0, 2.2, 1.45], gap="large")

# ================= 왼쪽: 검색 범위 및 필터 =================
with left:
    st.markdown("### 검색 범위 및 필터")
    if REAL:
        st.markdown(f"**Windows 계정**: `{html.escape(svc.identity.principal)}`")
        st.markdown('<div class="notice">검색 결과는 이 계정이 운영 체제에서 실제로 읽을 수 있는 파일로 제한되며, '
                    "결과를 보여주기 직전에 접근 가능 여부를 다시 확인합니다.</div>", unsafe_allow_html=True)
        level = "본문 검색" if svc.config.full_text else "메타데이터 전용"
        st.markdown(badge_html("색인 수준: " + level, "ok" if svc.config.full_text else "cat"), unsafe_allow_html=True)
    else:
        st.selectbox("가상 사용자 선택", options=[u.user_id for u in svc.access.users()],
                     format_func=lambda uid: svc.access.get_user(uid).name, key="user_id", on_change=on_user_change)
        st.markdown('<div class="warnbox">⚠ 교육용 <b>가상 사용자</b> 전환입니다. 실제 회사 인증(SSO/AD)이 아니며, '
                    "운영 시에는 사내 인증·원본 시스템 ACL 연동이 필요합니다.</div>", unsafe_allow_html=True)
    st.metric("접근 가능한 통합 문서 수", len(visible_all))

    # --- 위치 (공유폴더별 다중 경로 / 그룹웨어 / 업무시스템)
    locs = loc_options(visible_all)
    ss.f_locs = [k for k in ss.f_locs if k in locs]
    st.multiselect("위치 (비워두면 전체)", list(locs), key="f_locs", on_change=on_option_change,
                   format_func=lambda k: f"{locs[k][0]} ({locs[k][1]})")

    # --- 문서 유형
    type_counts: dict[str, int] = {}
    for d in visible_all:
        type_counts[d.file_type] = type_counts.get(d.file_type, 0) + 1
    type_opts = [t for t in TYPE_ORDER if t in type_counts]
    ss.f_types = [t for t in ss.f_types if t in type_opts]
    st.multiselect("문서 유형 (비워두면 전체)", type_opts, key="f_types", on_change=on_option_change,
                   format_func=lambda t: f"{FILE_TYPES[t]} ({type_counts[t]})")

    st.multiselect("문서 분류 (비워두면 전체)", CATEGORIES, key="f_cats", on_change=on_option_change)

    # --- 수정일
    st.radio("수정일", DATE_PRESETS, key="date_preset", on_change=on_option_change, horizontal=True)
    if ss.date_preset == "직접 지정":
        ref = reference_date(visible_all)
        st.date_input("수정일 범위", value=(ref - timedelta(days=30), ref), key="date_range",
                      on_change=on_option_change)
    elif ss.date_preset != "전체":
        st.caption(f"기준일: 접근 가능한 자료의 가장 최근 수정일 ({reference_date(visible_all).isoformat()})")

    st.button("필터 초기화", on_click=on_reset_filters)

    # --- 저장소 상태 / 색인 갱신
    st.markdown("**연결된 저장소**")
    statuses = {s["source_key"]: s for s in svc.indexer.source_statuses()}
    if not svc.connectors:
        st.warning("연결된 저장소가 없습니다.")
    for conn in svc.connectors:
        stt = statuses.get(conn.source_key)
        n = sum(1 for d in visible_all if d.source_key == conn.source_key)
        state = (badge_html("미동기화", "warn") if stt is None else
                 badge_html("정상", "ok") if stt["status"] == "ok" else badge_html("연결 오류·검색 제외", "warn"))
        st.markdown(f"{badge_html(conn.source_label, SOURCE_KIND.get(conn.source_key, 'cat'))} {state} "
                    f"문서 {n if stt and stt['status'] == 'ok' else '-'}건", unsafe_allow_html=True)
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

    # --- 공유폴더(UNC) 등록: 관리자 전용
    if svc.shares is not None and not REAL:
        if user and user.role == "admin":
            with st.expander("공유폴더(UNC) 등록 · 관리 (관리자)"):
                st.caption("PoC: UNC 경로는 표시용이며 실제 SMB 접속은 하지 않습니다. "
                           "각 UNC 경로는 data/shared_folder 아래 가상 폴더에 연결됩니다.")
                if ss.flash:
                    getattr(st, ss.flash[0])(ss.flash[1])
                    ss.flash = None
                for i, sh in enumerate(svc.shares.list()):
                    st.markdown(f"**{html.escape(sh.name)}**", unsafe_allow_html=True)
                    st.code(sh.unc_root, language=None)
                    c1, c2 = st.columns(2)
                    ek = f"share_en_{i}"
                    ss[ek] = sh.enabled
                    c1.checkbox("검색에 사용", key=ek, on_change=on_toggle_share, args=(sh.name, ek))
                    c2.button("등록 해제", key=f"unreg_{i}", on_click=on_unregister, args=(sh.name,))
                with st.form("share_form", clear_on_submit=True):
                    n_name = st.text_input("표시 이름", placeholder="예) 신계약팀 공유")
                    n_unc = st.text_input("UNC 경로", placeholder="\\\\서버이름\\공유이름\\폴더")
                    dirs = svc.shares.unregistered_dirs()
                    n_dir = st.selectbox("연결할 가상 폴더", dirs) if dirs else None
                    if not dirs:
                        st.caption("등록 가능한 가상 폴더가 없습니다 (data/shared_folder 아래에 폴더를 추가하세요).")
                    if st.form_submit_button("등록", disabled=not dirs):
                        on_register(n_name, n_unc, n_dir or "")
                        st.rerun()
        else:
            st.caption("공유폴더 등록·해제는 관리자만 할 수 있습니다.")

# ================= 가운데: 검색 결과 =================
with center:
    st.title("🔎 계리 업무자료 AI 통합검색")
    if REAL:
        st.caption("등록한 공유폴더에서 현재 Windows 계정이 읽을 수 있는 문서를 검색하고, 일치 위치와 원본 경로를 확인합니다.")
        if not svc.config.full_text:
            st.markdown('<div class="notice">🔒 <b>메타데이터 전용 모드</b>: 파일 이름·경로·형식·수정일만 검색합니다. '
                        "파일 내용은 읽지 않습니다. 본문 검색은 보안 승인 후 ‘초기 설정’에서 켤 수 있습니다.</div>",
                        unsafe_allow_html=True)
        if svc.storage is not None and not svc.storage.allow_body:
            st.error("로컬 색인 저장 위치의 보호를 확인하지 못해 **본문 검색·본문 표시가 차단**되었습니다 (파일명·경로만 검색). "
                     "‘⚙ 초기 설정’의 안내를 확인하세요.")
        if svc.indexer.count_documents() == 0:
            st.warning("색인된 문서가 없습니다. ‘⚙ 초기 설정’에서 공유폴더를 등록하고 색인을 생성하세요.")
    else:
        st.caption("여러 공유폴더·그룹웨어·업무시스템의 가상 자료를 한 번에 검색하고, 일치 위치와 원본 경로를 확인합니다. "
                   "(교육용 PoC · 가상 더미데이터)")

    with st.form("search_form"):
        st.text_input("검색어 또는 질문", key="query_text",
                      placeholder="예) RAFM 모델 실행 오류가 나면 어떻게 대응하나요?  /  결산 일정  /  E101")
        st.form_submit_button("검색", on_click=on_submit)
    o1, o2, o3, o4 = st.columns([3.1, 1.2, 0.9, 1.0])
    o1.radio("검색 대상", list(SCOPES), format_func=SCOPE_LABELS.get, key="scope", horizontal=True,
             on_change=on_option_change)
    o2.selectbox("정렬", list(SORTS), format_func=SORT_LABELS.get, key="sort", on_change=on_option_change)
    o3.selectbox("결과 수", [5, 10, 20], key="top_k", on_change=on_option_change)
    o4.toggle("내림차순", key="sort_desc", on_change=on_option_change)

    st.caption("추천 검색")
    scols = st.columns(len(SUGGESTIONS))
    for i, q in enumerate(SUGGESTIONS):
        scols[i].button(q, key=f"sug_{i}", on_click=on_suggest, args=(q,))

    with st.expander("답변 모드 설정 (선택)"):
        st.toggle("AI 답변 모드 (선택 기능)", key="mode_ai",
                  help="끄면 로컬 검색 모드(기본): 외부 AI 없이 일치한 원문 위치만 표시합니다.")
        st.checkbox("Mock LLM 사용 (구조 테스트용 · 실제 생성형 AI 아님)", key="use_mock")
        if ss.mode_ai and not ss.use_mock and settings.llm_provider != "mock":
            st.info("실제 LLM은 연결되지 않았습니다(LLM_PROVIDER=none). 질문하면 로컬 검색 모드 결과로 대체됩니다.")
        st.caption(f"실제 생성형 AI 연결: **미연결** · LLM_PROVIDER={settings.llm_provider}")

    # --- 결과 영역 -------------------------------------------------------
    last = ss.last
    if last and last["user_id"] != ss.user_id:
        last = ss.last = None
    # 세션에 남은 이전 응답은 그릴 때마다 현재 접근권한·삭제·수정 여부로 재검증한다 (색인 세대가 같아도 파일 상태는 바뀔 수 있다)
    if last and (last["generation"] != svc.indexer.get_generation() or not svc.engine.revalidate_response(user, last["resp"])):
        run_search(last["query"], record=False, params=last["params"], mode=last["mode"])
        last = ss.last
        st.info("색인 또는 파일 접근 상태가 바뀌어 검색 결과를 다시 확인했습니다. 접근할 수 없는 문서는 표시되지 않습니다.")

    if last:
        resp, ans = last["resp"], last["ans"]
        terms = query_terms(resp)
        if resp.unavailable_sources:
            st.warning("⚠ 일부 저장소를 검색하지 못했습니다: " + ", ".join(resp.unavailable_sources)
                       + " — 나머지 저장소의 결과만 표시됩니다.")
        if resp.status == "empty_query":
            st.warning(resp.message)
        elif resp.status in ("no_sources", "denied"):
            st.error(resp.message)
        elif resp.status == "no_results":
            st.info("관련 문서를 찾지 못했습니다. 다른 표현이나 업무 용어(예: RAFM, GoC, 결산)로 검색하거나 "
                    "검색 대상·필터를 확인해 보세요.")
        else:
            active = []
            if ss.f_locs:
                active += [locs[k][0] for k in ss.f_locs if k in locs]
            active += [FILE_TYPES[t] for t in ss.f_types]
            active += list(ss.f_cats)
            if ss.date_preset != "전체":
                active.append(f"수정일 {ss.date_preset}")
            if ss.scope != "all":
                active.append(SCOPE_LABELS[ss.scope])
            if resp.counts_exact:
                head = (f"**검색 결과 {resp.total_matched}건** (정렬: {SORT_LABELS[ss.sort]} {'↓' if ss.sort_desc else '↑'}"
                        + (f", 상위 {len(resp.results)}건 표시" if resp.total_matched > len(resp.results) else "") + ")")
            else:  # 실제 모드: 전체 일치 건수는 권한 확인 전이라 알리지 않고, 접근 확인이 끝난 표시 결과만 안내한다
                head = (f"**접근 확인된 검색 결과 {len(resp.results)}건 표시** (정렬: {SORT_LABELS[ss.sort]} "
                        f"{'↓' if ss.sort_desc else '↑'}, 접근 권한이 확인된 문서만 보여 줍니다)")
            st.markdown(
                head
                + ("<br>" + " ".join(f'<span class="chip">{html.escape(a)}</span>' for a in active) if active else ""),
                unsafe_allow_html=True)

            if ans.mode == "ai" and ans.status in ("ok", "insufficient"):
                with st.container(border=True):
                    st.markdown(f"**AI 답변 모드** · {html.escape(ans.llm_label)}")
                    if ans.is_mock:
                        st.markdown('<div class="notice">Mock 구조 테스트 응답입니다. 실제 생성형 AI가 만든 답변이 아니며 '
                                    "근거 문단 첫 문장을 규칙으로 이어 붙인 것입니다.</div>", unsafe_allow_html=True)
                    st.write(ans.answer_text)
                    for c in ans.citations:
                        loc = f" · {c.loc}" if c.loc else ""
                        st.button(f"[{c.number}] {c.title}{loc}", key=f"cite_{c.number}_{c.doc_id}_{c.chunk_seq}",
                                  on_click=on_select, args=(c.doc_id, c.chunk_seq))
            else:
                if ans.fallback_reason:
                    st.warning(ans.fallback_reason)
                st.markdown('<div class="notice">로컬 검색 모드: AI가 생성한 답변이 아니라, 권한이 있는 문서에서 찾은 '
                            "일치 위치와 원문입니다.</div>", unsafe_allow_html=True)

            for r in resp.results:
                is_sel = ss.selected is not None and ss.selected[0] == r.doc_id
                with st.container(border=True):
                    where = f" · {html.escape(r.share)}" if r.share else ""
                    st.markdown(
                        f'{type_badge(r.file_type)}<span class="rtitle">{html.escape(r.file_name or r.title)}</span>'
                        + (f' <span class="meta">({html.escape(r.title)})</span>' if r.file_name and r.file_name != r.title else "")
                        + (" ▶ <b>미리보기 중</b>" if is_sel else "")
                        + (f" {badge_html('원본 변경됨 · 색인 갱신 필요', 'warn')}" if r.stale else "")
                        + (f" {badge_html('본문 미색인', 'cat')}" if r.index_level == "metadata" else "")
                        + f'<div class="meta">{html.escape(path_label(r.source_key))}: '
                          f'<span class="path">{path_html(r.location)}</span></div>'
                        f'<div class="meta">{badge_html(r.source_system, SOURCE_KIND.get(r.source_key, "cat"))}'
                        f"{FILE_TYPES.get(r.file_type, r.file_type)} · 수정 {r.modified_at} · {html.escape(r.category)}{where}"
                        f" · v{html.escape(r.version)} · 관련도 {r.score}"
                        + (f" · 일치 {r.hit_count}곳" if r.hit_count else " · 파일명/경로 일치")
                        + "</div>", unsafe_allow_html=True)
                    if r.stale:
                        st.caption("원본 파일이 색인 이후 변경되어 과거 본문은 표시하지 않습니다. '색인 갱신' 후 다시 검색하세요.")
                    elif not r.passages:
                        st.caption("파일명·경로만 색인된 문서입니다 (본문 검색 비활성)." if r.index_level == "metadata"
                                   else "파일명/제목에서 일치했습니다. 본문 위치는 미리보기에서 확인하세요.")
                    for p in r.passages:
                        sel = is_sel and ss.selected[1] == p.chunk_seq
                        c1, c2 = st.columns([5, 1.4])
                        flag = " flag" if p.flagged else ""
                        warn = (f" {badge_html('⚠ 지시문 의심', 'warn')}" if p.flagged else "")
                        c1.markdown(
                            f'<div class="hit{flag}{" sel" if sel else ""}"><span class="loc">{html.escape(p.loc)}</span>'
                            f"{safe_highlight_html(make_snippet(p.text, p.matched_terms or terms), p.matched_terms or terms)}{warn}</div>",
                            unsafe_allow_html=True)
                        c2.button("위치 열기", key=f"loc_{r.doc_id}_{p.chunk_seq}", on_click=on_select,
                                  args=(r.doc_id, p.chunk_seq))
                    st.button("문서 미리보기", key=f"open_{r.doc_id}", on_click=on_select,
                              args=(r.doc_id, r.passages[0].chunk_seq if r.passages else None))
            if resp.analysis:
                with st.expander("검색어 해석 보기"):
                    st.write("정규화된 질문: ", resp.analysis.normalized)
                    for c in resp.analysis.concepts:
                        syn = [t for t, w in c.variants if t != c.term]
                        st.write(f"- **{c.term}**" + (" (일반어)" if c.generic else "")
                                 + (f" ≈ {', '.join(syn)}" if syn else ""))
    else:
        st.markdown('<div class="notice">검색어를 입력하거나 추천 검색을 선택하세요. 아래는 현재 필터 범위에서 '
                    "접근할 수 있는 문서 목록입니다 (파일명 기준).</div>", unsafe_allow_html=True)
        d_from, d_to = date_bounds(visible_all)
        browse = svc.engine.refine(  # visible_all 은 이번 렌더링에서 이미 재검증됨 → 같은 정책으로 좁히기만 한다
            visible_all, ss.f_cats or None, file_types=ss.f_types or None, locations=ss.f_locs or None,
            modified_from=d_from, modified_to=d_to)
        keyf = {"relevance": lambda d: d.modified_at, "modified": lambda d: d.modified_at,
                "name": lambda d: (d.file_name or d.title).casefold(), "type": lambda d: d.file_type,
                "path": lambda d: d.location.casefold()}[ss.sort]
        browse = sorted(browse, key=keyf, reverse=ss.sort_desc)
        st.markdown(f"**문서 {len(browse)}건**")
        for d in browse[:30]:
            c1, c2 = st.columns([6, 1])
            c1.markdown(f'{type_badge(d.file_type)}<span class="rtitle">{html.escape(d.file_name or d.title)}</span>'
                        f'<div class="meta"><span class="path">{path_html(d.location)}</span></div>'
                        f'<div class="meta">{FILE_TYPES.get(d.file_type, d.file_type)} · 수정 {d.modified_at} · '
                        f"{html.escape(d.category)}</div>", unsafe_allow_html=True)
            c2.button("미리보기", key=f"browse_{d.doc_id}", on_click=on_select, args=(d.doc_id, None))

    # --- 이전 질문/답변 (매 렌더링마다 권한·내용 재검증) ---------------------
    st.markdown("##### 이전 검색 내역")
    shown = revalidate_history(ss.history, user, svc.indexer, svc.access)
    if not shown:
        st.caption("이전 검색이 없습니다.")
    for de in shown[:8]:
        e = de.entry
        with st.expander(f"{e.created_at} · {e.query}"):
            if de.hidden:
                st.warning(HIDDEN_NOTICE)
            else:
                st.markdown(f"*{'AI 답변 모드' if e.mode == 'ai' else '로컬 검색 모드'}*")
                st.write(e.answer_text)
            st.button("다시 검색", key=f"redo_{e.entry_id}", on_click=on_suggest, args=(e.query,))

# ================= 오른쪽: 관련 원문 미리보기 =================
with right:
    st.markdown("### 관련 원문 미리보기")
    sel = ss.selected
    opened = svc.engine.open_document(user, sel[0]) if sel else None
    last_q = ss.last["query"] if ss.last else ""
    resp_terms = query_terms(ss.last["resp"]) if ss.last else ()
    if not sel:
        st.markdown('<div class="notice">검색 결과의 <b>위치 열기</b> 또는 <b>문서 미리보기</b> 버튼을 선택하면 '
                    "일치 단어가 강조된 원문이 여기에 표시됩니다.</div>", unsafe_allow_html=True)
    elif opened is None:
        st.warning("이 문서를 열 수 없습니다. 문서가 삭제되었거나 열람 권한이 없습니다.")
    else:
        doc, chunks = opened
        st.markdown(f"#### {html.escape(doc.file_name or doc.title)}")
        st.markdown(type_badge(doc.file_type) + badge_html(doc.source_system, SOURCE_KIND.get(doc.source_key, "cat"))
                    + badge_html(doc.category, "cat")
                    + (badge_html("원본 변경됨 · 색인 갱신 필요", "warn") if svc.access.is_stale(doc) else ""),
                    unsafe_allow_html=True)
        if svc.access.is_stale(doc):
            st.warning("원본 파일이 색인 이후 변경되어 과거 본문은 표시하지 않습니다. '색인 갱신' 후 다시 확인하세요.")
        elif doc.index_level == "metadata":
            st.info("이 문서는 파일 이름·경로·형식·수정일만 색인되어 본문 미리보기가 없습니다 (메타데이터 전용 모드이거나 본문 추출을 지원하지 않는 형식).")
        st.markdown(f"**{path_label(doc.source_key)}** (오른쪽 위 아이콘으로 복사)")
        st.code(doc.location, language=None)
        if doc.source_key == "shared_folder":
            st.markdown("**상위 폴더 경로**")
            st.code(folder_of(doc.location), language=None)
        st.markdown(
            f"- **문서**: {html.escape(doc.title)} (`{doc.doc_id}`)\n- **형식**: {FILE_TYPES.get(doc.file_type, doc.file_type)}\n"
            f"- **버전 / 최종 수정일**: {doc.version} / {doc.modified_at}\n- **담당 부서**: {doc.department}\n"
            + (f"- **공유폴더**: {doc.share}\n" if doc.share else ""))
        if doc.location_detail:
            st.caption(doc.location_detail)
        st.caption("가상 원본 경로입니다(예약 도메인 .invalid). 실제 시스템에는 연결되지 않습니다.")

        # --- 일치 위치 이동
        matches = svc.engine.matching_chunks(user, doc.doc_id, last_q) if last_q else []
        seqs = [m[0] for m in matches]
        cur = sel[1]
        if matches:
            idx = seqs.index(cur) if cur in seqs else -1
            st.markdown(f"**일치 위치 {len(matches)}곳** " + (f"· 현재 {idx + 1}/{len(matches)}" if idx >= 0 else ""))
            n1, n2 = st.columns(2)
            n1.button("◀ 이전 일치", key="nav_prev", disabled=not matches, on_click=on_select,
                      args=(doc.doc_id, seqs[(idx - 1) % len(seqs)] if idx >= 0 else seqs[-1]))
            n2.button("다음 일치 ▶", key="nav_next", disabled=not matches, on_click=on_select,
                      args=(doc.doc_id, seqs[(idx + 1) % len(seqs)] if idx >= 0 else seqs[0]))
            for seq, loc, _score in matches[:12]:
                st.button(("● " if seq == cur else "○ ") + (loc or f"문단 {seq + 1}"), key=f"jump_{seq}",
                          on_click=on_select, args=(doc.doc_id, seq))
        elif last_q:
            st.caption("이 문서에는 현재 검색어와 일치하는 본문 위치가 없습니다 (파일명/제목 일치일 수 있습니다).")

        st.toggle("일치한 문단만 보기", key="only_matches", disabled=not matches)
        st.markdown("**원문** (선택한 위치는 노란색, 일치 단어는 형광펜)")
        by_seq = {c.seq: c for c in chunks}
        show = [c for c in chunks if (not ss.only_matches or c.seq in seqs or c.seq == cur)]
        for ch in show:
            is_cur = cur == ch.seq
            cls = "passage" + (" sel" if is_cur else "") + (" flag" if ch.flagged else "") + \
                  ("" if is_cur or ch.seq in seqs or not matches else " dim")
            head = f"<b>{html.escape(ch.heading)}</b><br>" if ch.heading and ch.heading != doc.title else ""
            warn = (f'<br>{badge_html("⚠ 지시문 의심: " + ch.flag_reason, "warn")} 문서 속 문장은 실행되지 않습니다.'
                    if ch.flagged else "")
            st.markdown(f'<div class="{cls}"><span class="loc">📍 {html.escape(ch.loc)}</span>{head}'
                        f"{safe_highlight_html(ch.text, resp_terms)}{warn}</div>", unsafe_allow_html=True)
        if doc.attachments:
            st.caption("첨부파일(목록만 수집): " + ", ".join(doc.attachments))
