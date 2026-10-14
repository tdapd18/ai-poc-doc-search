"""초기 설정 화면(실제 Windows 모드): ① 보안 모드 → ② 공유폴더 등록 → ③ 연결 테스트 → ④ 색인 생성.

- 연결 테스트와 사전 점검은 **파일 내용을 읽지 않는다** (목록 + 열기 가능 여부만).
- 본문 색인은 보안 승인 확인 기록이 있어야 켤 수 있다.
- 모든 상태 변경은 감사 로그에 건수/상태만 남긴다.
"""
from __future__ import annotations

import html

from core.app_config import APPROVAL_STATEMENT, ConfigError
from core.fs import FileSystem
from core.services import Services, apply_index_mode, sync_with_audit
from core.setup_check import ConnectionTestResult, check_share
from core.shares import ShareError

MODE_LABELS = {
    "metadata_only": "메타데이터 전용 (기본·권장) — 파일 이름·경로·형식·수정일만 색인, 내용은 읽지 않음",
    "full_text": "본문 검색 — 파일 내용을 추출해 이 PC의 로컬 색인에 저장 (보안 승인 필요)",
}
CODE_HELP = {
    "invalid_path": "UNC 경로는 \\\\서버이름\\공유이름\\폴더 형식이어야 합니다.",
    "denied": "공유 또는 NTFS 권한이 없습니다. 권한 신청 후 다시 테스트하세요. (다른 계정으로 로그인한 상태인지도 확인)",
    "not_found": "서버 이름·공유 이름 철자를 확인하세요. 경로가 변경되었을 수도 있습니다.",
    "unavailable": "사내망 또는 VPN 연결, 서버 상태, 방화벽(SMB 445)을 확인하세요.",
}


def _flash(ss, kind: str, msg: str) -> None:
    ss["setup_flash"] = (kind, msg)


def _fs(svc: Services, share) -> FileSystem:
    return svc.connector.fs_for(share)


def render_result(st, res: ConnectionTestResult) -> None:
    if not res.ok:
        st.error(f"연결 테스트 실패 ({res.stage}): {res.message}")
        if res.code in CODE_HELP:
            st.caption("조치: " + CODE_HELP[res.code])
        return
    st.success(f"연결 성공 · 응답 {res.latency_ms}ms · 최상위 폴더 {res.top_folders}개, 파일 {res.top_files}개")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("색인 대상 파일(추정)", res.indexable)
    c2.metric("점검한 항목", res.scanned_entries)
    c3.metric("권한 표본 읽기 가능", f"{res.readable}/{res.sampled}")
    c4.metric("용량(MB, 추정)", round(res.total_bytes / 1024 / 1024, 1))
    if res.by_ext:
        st.caption("형식별 파일 수: " + ", ".join(f"{k} {v}" for k, v in sorted(res.by_ext.items(), key=lambda x: -x[1]))
                   + (f" · 구형(파일명만) {res.legacy}" if res.legacy else "")
                   + (f" · 미지원 {res.unsupported}" if res.unsupported else ""))
    for w in res.warnings:
        st.warning(w)
    st.caption("이 테스트는 파일 내용을 읽지 않았습니다 (폴더 목록과 열기 가능 여부만 확인).")


def render_setup(st, svc: Services, ss) -> None:
    cfg, store = svc.config, svc.config_store
    shares = svc.shares.list()
    tests: dict = ss.setdefault("setup_tests", {})

    st.title("⚙ 초기 설정")
    st.caption(f"현재 Windows 계정: **{svc.identity.principal}** — 검색 결과는 이 계정이 운영 체제에서 읽을 수 있는 파일로 제한됩니다. "
               "이 PC에서만 동작하며 파일 내용이나 검색어를 외부로 전송하지 않습니다.")
    done = [
        ("보안 모드", True),
        ("공유폴더 등록", bool(shares)),
        ("연결 테스트", bool(shares) and all(tests.get(s.name) and tests[s.name].ok for s in shares if s.enabled)),
        ("색인 생성", svc.indexer.count_documents() > 0),
    ]
    st.markdown(" → ".join(("✅ " if ok else "⬜ ") + name for name, ok in done))
    if ss.get("setup_flash"):
        kind, msg = ss.pop("setup_flash")
        getattr(st, kind)(msg)

    # ---------------------------------------------------------------- 1. 보안 모드
    st.markdown("### 1. 보안 모드 (색인 수준)")
    st.markdown(f"현재: **{'본문 검색' if cfg.full_text else '메타데이터 전용'}**"
                + (f" · 승인 참조 `{html.escape(cfg.approval.approver)}` ({cfg.approval.approved_at})" if cfg.full_text else ""))
    choice = st.radio("색인 수준", list(MODE_LABELS), format_func=MODE_LABELS.get, key="setup_mode_choice",
                      index=1 if cfg.full_text else 0)
    ack, approver = False, ""
    if choice == "full_text" and not cfg.full_text:
        st.warning("본문 검색은 회사 정보보안 승인을 받은 경우에만 사용하세요. 이 확인은 절차적 통제이며 승인 자체를 증명하지 않습니다.")
        ack = st.checkbox(APPROVAL_STATEMENT, key="setup_ack")
        approver = st.text_input("승인 참조 (담당자 또는 승인 문서 번호)", key="setup_approver")
    if choice != cfg.index_mode or (choice == "full_text" and not cfg.full_text):
        if st.button("색인 수준 적용", key="setup_apply_mode"):
            try:
                changed = apply_index_mode(svc, choice, approver=approver, acknowledged=ack)
                _flash(ss, "success", "색인 수준을 변경했습니다. 보안을 위해 기존 색인을 삭제했으니 색인을 다시 생성하세요." if changed
                       else "변경 사항이 없습니다.")
                tests.clear()
            except ConfigError as exc:
                _flash(ss, "error", str(exc))
            st.rerun()
        st.caption("※ 수준을 바꾸면 기존 색인(본문 포함)을 모두 삭제합니다.")

    # ---------------------------------------------------------------- 2. 공유폴더 등록
    st.markdown("### 2. 공유폴더 경로 등록")
    st.caption("Windows UNC 경로(예: `\\\\서버이름\\공유이름\\폴더`)를 등록합니다. 관리자 공유(C$ 등)와 겹치는 경로는 등록할 수 없습니다.")
    with st.form("setup_register", clear_on_submit=True):
        name = st.text_input("표시 이름", placeholder="예) 계리평가팀 공유")
        unc = st.text_input("UNC 경로", placeholder="\\\\서버이름\\공유이름\\폴더")
        excl = st.text_input("제외할 폴더/파일 이름 패턴 (쉼표로 구분, 선택)", placeholder="예) Archive*, 개인*")
        if st.form_submit_button("공유폴더 등록"):
            try:
                svc.shares.register_unc(name, unc, [p for p in excl.split(",")])
                store.audit("share_registered", total=len(svc.shares.list()))
                _flash(ss, "success", f"'{name}' 공유폴더를 등록했습니다. 다음 단계에서 연결 테스트를 실행하세요.")
            except ShareError as exc:
                _flash(ss, "error", str(exc))
            st.rerun()
    for i, sh in enumerate(shares):
        c1, c2, c3 = st.columns([3, 1.2, 1])
        c1.markdown(f"**{html.escape(sh.name)}**")
        c1.code(sh.unc_root, language=None)
        if sh.exclude:
            c1.caption("제외 패턴: " + ", ".join(sh.exclude))
        en = c2.checkbox("색인에 사용", value=sh.enabled, key=f"setup_en_{i}")
        if en != sh.enabled:
            svc.shares.set_enabled(sh.name, en)
            tests.pop(sh.name, None)
            st.rerun()
        if c3.button("등록 해제", key=f"setup_unreg_{i}"):
            svc.shares.unregister(sh.name)
            tests.pop(sh.name, None)
            store.audit("share_unregistered", total=len(svc.shares.list()))
            _flash(ss, "success", f"'{sh.name}' 등록을 해제했습니다. 다음 색인 생성 때 해당 공유의 색인이 삭제됩니다.")
            st.rerun()
    if not shares:
        st.info("등록된 공유폴더가 없습니다.")

    # ---------------------------------------------------------------- 3. 연결 테스트
    st.markdown("### 3. 연결 테스트")
    st.caption("경로 접근, 응답 시간, 읽기 권한 표본, 형식별 파일 수를 점검합니다. **파일 내용은 읽지 않습니다.**")
    enabled = [s for s in shares if s.enabled]
    if st.button("전체 연결 테스트", key="setup_test_all", disabled=not enabled):
        for s in enabled:
            tests[s.name] = check_share(s, _fs(svc, s), cfg)
        store.audit("connection_test", shares=len(enabled), ok=sum(1 for s in enabled if tests[s.name].ok))
        st.rerun()
    for i, s in enumerate(enabled):
        st.markdown(f"**{html.escape(s.name)}**")
        if st.button("이 공유 테스트", key=f"setup_test_{i}"):
            tests[s.name] = check_share(s, _fs(svc, s), cfg)
            store.audit("connection_test", shares=1, ok=int(tests[s.name].ok))
            st.rerun()
        if s.name in tests:
            render_result(st, tests[s.name])

    # ---------------------------------------------------------------- 4. 색인 생성
    st.markdown("### 4. 색인 생성")
    ready = bool(enabled) and all(tests.get(s.name) and tests[s.name].ok for s in enabled)
    est = sum(tests[s.name].indexable for s in enabled if s.name in tests)
    level = "본문 검색(승인됨)" if cfg.full_text else "메타데이터 전용(내용 미열람)"
    st.markdown(f"색인 수준: **{level}** · 예상 대상 약 **{est}**개 파일" if ready else
                "모든 사용 중인 공유의 연결 테스트가 성공해야 색인을 만들 수 있습니다.")
    if st.button("색인 생성 시작", key="setup_run_index", disabled=not ready):
        bar, status = st.progress(0.0), st.empty()

        def on_progress(ev: dict) -> None:
            frac = min(ev["files"] / est, 0.99) if est else 0.0
            bar.progress(1.0 if ev.get("done") else frac)
            status.write(f"공유 '{ev['share']}' — 스캔한 파일 {ev['files']}개 · 색인된 문서 {ev['documents']}건")

        report = sync_with_audit(svc, on_progress)
        ss["sync_report"] = report
        svc.engine.invalidate_cache()
        _flash(ss, "success", f"색인 생성을 마쳤습니다. 현재 색인된 문서 {svc.indexer.count_documents()}건 — '🔎 검색' 화면에서 검색할 수 있습니다.")
        st.rerun()  # 단계 표시(✅)와 결과를 갱신된 상태로 다시 그린다
    if ss.get("sync_report") is not None:
        with st.expander("최근 색인 결과", expanded=True):
            for line in ss["sync_report"].summary_lines():
                st.text(line)
    with st.expander("색인 삭제 (이 PC에 저장된 색인을 모두 지웁니다)"):
        confirm = st.checkbox("로컬 색인(문서 목록·본문 포함)을 삭제하는 것을 확인합니다.", key="setup_del_confirm")
        if st.button("색인 삭제", key="setup_delete_index", disabled=not confirm):
            svc.indexer.reset()
            svc.engine.invalidate_cache()
            store.audit("index_deleted")
            _flash(ss, "success", "로컬 색인을 삭제했습니다.")
            st.rerun()
