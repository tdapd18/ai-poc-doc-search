# 자동 테스트 결과 (pytest)

- 전체 141건 중 통과 141건 / 실패 0건
- 데이터는 모두 가상 더미데이터이며 외부 네트워크·실제 LLM 호출은 없습니다 (LLM 관련은 Mock 구현으로 검증).

| 파일 | 테스트 | 입력조건 | 예상 결과 | 실제 결과 | 통과 |
|---|---|---|---|---|---|
| test_access_control.py | `test_visible_documents_differ_by_user` | 계리평가팀/재무팀/관리자 가상 사용자별 접근 가능 문서 | 계리 13건, 재무 7건, 관리자 15건 (관리자 전용 SF-004 는 계리 제외) | actuary=13, finance=7, admin=15 | ✅ |
| test_access_control.py | `test_unauthorized_documents_not_searchable` | 재무팀 사용자가 RAFM FAQ·GoC 매뉴얼·관리자 전용 문서 주제를 검색 | 권한 없는 문서(GW-001, SF-002, SF-004, BS-001 ...)가 결과에 전혀 없음 | 재무팀 결과 문서: ['BS-002', 'GW-002', 'SF-001', 'SF-101', 'SF-103', 'SF-201'] | ✅ |
| test_access_control.py | `test_admin_only_doc_hidden_from_actuary` | '예외 승인 내역' 검색 (계리 vs 관리자) | 계리평가팀은 SF-004 미노출, 관리자는 SF-004 노출 | 예상 결과와 일치 | ✅ |
| test_access_control.py | `test_no_side_channel_counts` | 계리 전용 문서와 겹치는 질문을 재무팀(접근 가능 문서 7건)이 검색, 비인가 문서 전용 주제도 검색 | 일치 건수·결과가 재무팀 접근 가능 문서(최대 7건)만으로 계산되고, 메시지에 '권한/제외' 등 비인가 문서 존재를 암시하는 표현 없음 | GoC 변동 분석 매뉴얼 → status=ok, total_matched=4, 결과=['SF-103', 'SF-001', 'BS-002', 'SF-101'] | ✅ |
| test_access_control.py | `test_unauthorized_preview_blocked` | 재무팀 사용자가 GW-001/SF-004 원문 열기 시도, 존재하지 않는 ID 열기 | 모두 None (존재/권한 여부를 구분하지 않음), 권한자는 열람 가능 | 예상 결과와 일치 | ✅ |
| test_access_control.py | `test_default_deny_rules` | ACL 이 비어 있는 문서, 알 수 없는 사용자, None 사용자 | 모두 거부 (기본 거부 정책) | 예상 결과와 일치 | ✅ |
| test_access_control.py | `test_unknown_user_gets_denied_search` | 등록되지 않은 사용자/None 으로 검색 | status=denied, 결과 없음 (비정상 종료 없음) | 예상 결과와 일치 | ✅ |
| test_access_control.py | `test_acl_grant_reflected_after_sync` | SF-002(GoC 매뉴얼)의 allowed_groups 에 finance 추가 후 색인 갱신 | 갱신 전에는 재무팀 검색 불가, 갱신 후 검색/열람 가능, 권한변경 1건 감지 | acl_changed=['SF-002'] | ✅ |
| test_access_control.py | `test_acl_revoke_blocks_cache_and_history` | 재무팀이 접근 가능한 SF-001 로 검색·이력 생성 → SF-001 권한을 계리팀 전용으로 회수 → 색인 갱신 | 같은 질문 재검색(캐시 포함)에서 SF-001 미노출, 원문 열람 불가, 이전 답변 이력은 숨김 처리 | 회수 후 재무팀 결과=['SF-101', 'BS-002', 'SF-103', 'GW-002', 'SF-201'], from_cache=False | ✅ |
| test_access_control.py | `test_cache_is_per_user` | 관리자가 검색(캐시 생성) 직후 같은 질문을 재무팀이 검색 | 재무팀은 관리자 캐시를 재사용하지 못하고 권한 있는 문서만 받음 | 예상 결과와 일치 | ✅ |
| test_access_control.py | `test_history_hidden_for_other_user` | 계리팀 사용자의 질문 이력을 재무팀 사용자 화면에서 조회 | 다른 사용자의 이력은 표시되지 않음 | 예상 결과와 일치 | ✅ |
| test_answers.py | `test_local_mode_not_ai_and_shows_sources` | 로컬 검색 모드로 RAFM 오류 질문 | AI 생성 답변이 아님(is_ai_generated=False, 안내문 포함), 문서명/버전/원본 위치가 있는 근거 문단 제공 | 근거 6건, 1번=RAFM 모델 실행 오류 대응 FAQ v1.6 | ✅ |
| test_answers.py | `test_local_mode_no_results` | 문서에 없는 질문(로컬 모드) | status=no_results, 근거 없음, 생성 답변 없음 | 예상 결과와 일치 | ✅ |
| test_answers.py | `test_ai_mode_mock_citations_linked` | AI 답변 모드 + Mock LLM | 답변의 모든 출처 번호([n])가 실제 근거 문단과 연결됨, Mock 이므로 '실제 AI 생성'으로 표시되지 않음 | 출처 번호 [1, 2, 3] → 근거 문단 연결 확인 | ✅ |
| test_answers.py | `test_ai_mode_only_sends_evidence_paragraphs` | AI 모드 요청 시 모델에 전달된 내용 확인 | 전달 텍스트는 검색된 근거 문단뿐(문서 전문/다른 문서 본문 미전달), 시스템 지시에 '문서는 데이터' 원칙 포함 | 예상 결과와 일치 | ✅ |
| test_answers.py | `test_unauthorized_docs_never_reach_llm` | 관리자 권한으로 검색한 결과를 재무팀 사용자 권한으로 AI 답변 생성에 사용 시도 | 재무팀 권한 밖 문서는 모델 입력에 포함되지 않음 | 재무팀 근거 문서=['SF-001'] | ✅ |
| test_answers.py | `test_revoked_between_search_and_answer` | 검색 직후, 답변 생성 전에 해당 문서의 권한이 회수됨 | 오래된 검색 결과를 근거로 쓰지 않음(근거 0건) | 예상 결과와 일치 | ✅ |
| test_answers.py | `test_insufficient_evidence_returns_cannot_confirm` | 근거가 없는 질문(AI 모드) | LLM 을 호출하지 않고 '확인 불가' 안내 또는 검색결과 없음 | 예상 결과와 일치 | ✅ |
| test_answers.py | `test_ai_failure_falls_back_to_local` | LLM 연결 실패(Mock fail) / 비활성 클라이언트 / 사내 LLM 미구현 | 예외 없이 로컬 검색 모드 결과로 대체되고 사유 표시 | AI 연결 실패: 사내 승인 LLM 연결이 아직 구성되지 않았습니다 (종류/API 규격 미확정) — 로컬 검 | ✅ |
| test_answers.py | `test_invalid_llm_citations_rejected` | 출처 번호가 없는/존재하지 않는 답변을 LLM 이 반환 | 해당 답변을 사용하지 않고 로컬 모드로 대체 | 예상 결과와 일치 | ✅ |
| test_answers.py | `test_real_llm_flag_defaults_false` | 제공된 모든 LLM 구현체 | 실제 LLM 연결(is_real)은 하나도 없음 — 연결 완료로 표시하지 않음 | 예상 결과와 일치 | ✅ |
| test_answers.py | `test_prompt_injection_detected_in_data` | GW-003 게시글 댓글에 '이전 지시 무시/권한 변경/외부 전송' 악성 문장이 포함됨 | 색인 시 해당 문단이 지시문 의심(flagged)으로 표시됨, 정상 문단은 표시되지 않음 | 예상 결과와 일치 | ✅ |
| test_answers.py | `test_injection_never_sent_to_llm_nor_executed` | 악성 문장이 든 문서가 검색되는 질문(AI 모드) 후 상태 확인 | 의심 문단은 LLM 입력에 없음, 사용자 권한/설정은 그대로, 어떤 외부 호출·설정 변경도 일어나지 않음 | 의심 문단 0건 표시(경고), LLM 전달 0건 | ✅ |
| test_answers.py | `test_detect_injection_patterns` | 다양한 지시문 표현과 정상 업무 문장 | 지시문은 탐지, 정상 업무 문장은 오탐하지 않음 | 예상 결과와 일치 | ✅ |
| test_answers.py | `test_chunk_splitting_keeps_tables_and_headings` | 제목·표·문단이 섞인 마크다운 | 제목이 문단의 heading 으로 유지되고 표는 하나의 문단으로 유지 | 예상 결과와 일치 | ✅ |
| test_answers.py | `test_html_is_escaped_in_highlight` | 본문에 <script> 가 포함된 악성 문서 텍스트를 화면 표시용으로 변환 | HTML 이 이스케이프되어 실행되지 않고, 검색어만 강조됨 | 예상 결과와 일치 | ✅ |
| test_answers.py | `test_logs_do_not_contain_query_body_or_secrets` | 비밀번호·API 키 형태 문자열이 포함된 검색어로 검색/동기화 | 로그에 검색어 원문, 문서 본문, 비밀번호/키가 기록되지 않음 | 예상 결과와 일치 | ✅ |
| test_answers.py | `test_redact_filter_masks_secrets` | 비밀번호/토큰 패턴이 들어 있는 로그 문자열 | [REDACTED] 로 마스킹 | 예상 결과와 일치 | ✅ |
| test_app_smoke.py | `test_app_starts_with_three_sources` | 웹앱 첫 실행 | 예외 없이 기동, 자동 색인으로 계리평가팀 기준 13건 표시 | 앱 기동·자동 색인 확인 | ✅ |
| test_app_smoke.py | `test_search_select_source_and_preview` | 추천 질문 클릭 → 두 번째 결과의 '문서 미리보기' 클릭 | 검색 결과가 표시되고, 오른쪽 패널에 선택한 문서의 문서명/버전/원본 위치가 나타남 | 검색→출처 선택→원문/원본 위치 표시 확인 | ✅ |
| test_app_smoke.py | `test_empty_query_shows_warning` | 검색어 없이 검색 버튼 | 경고 안내, 앱 중단 없음 | 예상 결과와 일치 | ✅ |
| test_app_smoke.py | `test_user_switch_changes_visible_documents` | 가상 사용자를 재무팀으로 전환 | 접근 가능 문서 수 13 → 7, 계리 전용 문서 제목이 문서 목록(첫 화면)에서 사라짐 | 재무팀 7건 표시 | ✅ |
| test_app_smoke.py | `test_refresh_button_and_revocation_hides_old_answer` | 재무팀 검색 후 SF-001 권한 회수 → 색인 갱신 버튼 | 갱신 후 결과·근거 패널에서 SF-001 내용이 사라지고, 이전 답변 이력은 숨김 안내가 표시됨 | 권한 회수 후 결과/원문/이력에서 SF-001 노출 없음 | ✅ |
| test_app_ux.py | `test_three_panels_and_result_summary` | 앱 실행 후 검색 | 왼쪽 '검색 범위 및 필터', 가운데 '검색 결과 N건', 오른쪽 '관련 원문 미리보기' 영역이 모두 표시됨 | 3개 영역 제목 + 결과 건수 표시 | ✅ |
| test_app_ux.py | `test_rows_show_name_type_date_unc_and_locations` | 'E101 오류 조치' 검색, 결과 20건 | 결과 행에 파일 형식 배지, 파일명, 수정일, 원본 UNC 경로, PDF 쪽/Excel 시트·셀/PPT 슬라이드 위치가 표시됨 | PDF p.2 / Excel 시트·셀 / PPT 슬라이드 3 / UNC / 수정일 표시 확인 | ✅ |
| test_app_ux.py | `test_filters_change_results_immediately` | 검색 후 문서 유형 필터(PDF)·위치 필터·수정일 프리셋을 차례로 변경 (검색 버튼 재클릭 없음) | 변경 즉시 결과가 필터에 맞게 다시 계산됨 | 전체 6건 → PDF만 / 계리평가 공유만 / 최근 7일 필터가 즉시 반영 | ✅ |
| test_app_ux.py | `test_scope_and_sort_change_rerun_search` | 검색 후 검색 대상을 '파일명만'으로, 정렬을 '파일명' 오름차순으로 변경 | 같은 검색어로 즉시 다시 검색되어 파일명 일치 결과만 나오고 파일명순으로 정렬됨 | 예상 결과와 일치 | ✅ |
| test_app_ux.py | `test_select_location_updates_preview_and_path` | PDF 결과의 '위치 열기' 버튼 선택 | 오른쪽 미리보기에 해당 문서의 UNC 경로(복사용 코드 블록)·상위 폴더 경로가 나오고 선택 위치가 기록됨 | 선택 문서에 따라 미리보기 경로 코드 블록 변경 | ✅ |
| test_app_ux.py | `test_prev_next_match_navigation` | 일치 위치가 여러 곳인 문서에서 '다음 일치'를 반복 클릭한 뒤 '이전 일치' 클릭 | 선택 위치가 문서 순서대로(오름차순) 이동하다가 처음으로 순환하고, '이전 일치'는 한 칸 되돌아감 | 이동 순서(문단 번호): [0, 1, 2, 3, 4, 5] 후 처음으로 순환 | ✅ |
| test_app_ux.py | `test_browse_list_before_search_and_reset_filters` | 검색 전 첫 화면, 필터 지정 후 '필터 초기화' | 접근 가능한 문서 13건 목록(파일명·UNC 경로)이 보이고, 초기화하면 모든 필터가 해제됨 | 예상 결과와 일치 | ✅ |
| test_app_ux.py | `test_location_options_hide_unauthorized_shares` | 계리팀 / 재무팀 / 관리자 사용자의 위치 필터 선택지 | 접근 가능한 문서가 있는 위치만 노출 ('관리자 전용' 공유는 관리자에게만) | 재무팀 위치 선택지: 공유폴더 · 계리평가 공유 (3), 공유폴더 · 재무팀 공유 (2), 그룹웨어 (1), 업무시스템 (1) | ✅ |
| test_app_ux.py | `test_share_registration_admin_only` | 일반 사용자 / 관리자 화면에서 공유폴더 등록 UI, 잘못된 UNC 와 올바른 UNC 등록 | 일반 사용자에게는 등록 UI 없음, 관리자는 등록 가능(잘못된 UNC 는 오류 안내), 등록 후 새 공유 문서가 검색됨 | \\fs-new01.example.invalid\신계약\메모.md | ✅ |
| test_app_ux.py | `test_unauthorized_document_never_shown_in_ui` | 재무팀으로 전환해 계리 전용 문서(Excel SF-102, FAQ)가 걸리는 질문 검색 | 결과·미리보기·경로 코드 블록 어디에도 비인가 문서 경로/제목이 나타나지 않음 | 예상 결과와 일치 | ✅ |
| test_app_ux.py | `test_ai_mode_mock_still_available_with_locations` | AI 답변 모드 + Mock LLM 으로 검색 | Mock 고지 문구와 출처 버튼([n] 문서명 · 위치)이 표시되고, 실제 AI 가 아니라는 표시 유지 | 예상 결과와 일치 | ✅ |
| test_browser.py | `test_search_highlight_and_copy_unc_path` | 브라우저에서 '내부통제 점검 보고서 E101' 검색 → 1위 PDF 결과의 미리보기에서 경로 복사 버튼 클릭 | 결과와 미리보기에 일치 단어 강조(mark)가 있고, 클립보드에 원본 UNC 경로가 정확히 복사됨 | 클립보드: \\fs-actu01.example.invalid\계리평가\결산검증\결산_내부통제_점검보고서.pdf | ✅ |
| test_browser.py | `test_filter_select_and_copy_other_result` | 'E101 오류 조치' 검색 후 문서 유형 필터에서 PowerPoint 선택, PPT 결과의 '위치 열기' 클릭 후 경로 복사 | 결과가 PPTX 만 남고(슬라이드 3 위치), 미리보기가 PPT 문서로 바뀌며 클립보드에 PPT 의 UNC 경로가 복사됨 | 위치 열기 버튼 11개 → 필터 후 PPT만, 복사: \\fs-actu01.example.invalid\계리평가\교육자료\월말결산_킥오프_자료.pptx | ✅ |
| test_browser.py | `test_user_switch_hides_unauthorized_in_browser` | 브라우저에서 사용자를 재무팀으로 전환해 계리 전용 Excel/FAQ 가 걸리는 검색 | 화면 어디에도 비인가 문서 제목이 나타나지 않음 | 예상 결과와 일치 | ✅ |
| test_connectors.py | `test_three_connectors_collect_documents` | 가상 저장소 3개(공유폴더/그룹웨어/업무시스템) 수집 | 공유폴더 9(md/txt/pdf/xlsx/pptx), 그룹웨어 3, 업무시스템 3건 — 총 15건, 형식 오류 없음 | {'공유폴더': 9, '그룹웨어': 3, '업무시스템': 3} | ✅ |
| test_connectors.py | `test_common_schema_has_all_metadata` | 세 Connector 수집 결과 | 모든 문서가 공통 메타데이터(ID/문서명/시스템/분류/버전/작성·수정일/부서/위치/본문)를 가짐 | 예상 결과와 일치 | ✅ |
| test_connectors.py | `test_doc_ids_unique_across_sources` | 세 저장소 전체 문서 | 문서 ID 중복 없음 | 예상 결과와 일치 | ✅ |
| test_connectors.py | `test_shared_folder_recursion_and_change_detection` | 하위 폴더 포함 공유폴더 스캔 후 파일 추가/수정/삭제 | 하위 폴더 파일 탐색, 신규/변경/삭제 파일이 각각 감지됨 | {'new': ['계리평가/가정관리/새문서.txt'], 'changed': ['계리평가/분석매뉴얼/GoC_단위_변동분석_매뉴얼.md'], 'removed': ['계리평가/결산검증/IFRS17_결산검증가이드.md']} | ✅ |
| test_connectors.py | `test_groupware_keeps_url_and_attachments` | 그룹웨어 게시글 수집 | 게시글 고유 ID(GW-xxx)와 가상 원본 URL, 첨부파일 정보를 보존 | 예상 결과와 일치 | ✅ |
| test_connectors.py | `test_business_system_preserves_id_and_screen_path` | 업무시스템 레코드 수집 | 업무시스템 ID(BS-xxx)와 원본 화면 위치 보존, 구조화 표가 텍스트 표로 변환됨 | 예상 결과와 일치 | ✅ |
| test_connectors.py | `test_invalid_documents_are_reported_not_crashing` | 잘못된 형식 문서 5종(메타데이터 없음/필수 누락/날짜 오류/깨진 JSON/비UTF-8) | 예외 없이 invalid 목록에 사유만 기록, 정상 문서는 계속 수집, 사유에 본문 내용이 없음 | 공유폴더 invalid=['계리평가 공유/bad1.md', '계리평가 공유/bad2.md', '계리평가 공유/bad3.md'], 그룹웨어 invalid=['broken.json'] | ✅ |
| test_connectors.py | `test_duplicate_id_in_same_source` | 같은 문서 ID(SF-001)를 가진 두 번째 파일 추가 | 하나만 채택하고 중복 목록/오류 항목에 기록 | 예상 결과와 일치 | ✅ |
| test_connectors.py | `test_missing_root_raises_connector_error` | 존재하지 않는 저장소 경로 | ConnectorError (저장소 단위 오류로 상위에서 격리 처리) | 예상 결과와 일치 | ✅ |
| test_connectors.py | `test_business_record_with_bad_table_is_invalid` | 표의 행 길이가 컬럼 수와 다른 업무시스템 레코드 | 해당 레코드만 invalid, 나머지 정상 | 예상 결과와 일치 | ✅ |
| test_extractors.py | `test_xlsx_sheet_and_cell_locations` | 실제 Excel 파일(3개 시트)을 표준 라이브러리 추출기로 읽음 | 행마다 '시트 'X' · 셀 A2:E2' 위치와 '머리글: 값' 텍스트가 만들어지고 3개 시트가 모두 포함됨 | 11개 행 조각, 예: 시트 '요약' · 셀 A3:E3 | ✅ |
| test_extractors.py | `test_pptx_slide_locations_title_table_notes` | 실제 PowerPoint 파일(5장) | 슬라이드 번호 위치, 제목, 표 행, 발표자 노트가 추출됨 | 슬라이드 5장, 3번 슬라이드 노트 포함 | ✅ |
| test_extractors.py | `test_pdf_page_locations` | 실제 PDF 파일(3쪽, 한글, UniKS-UCS2-H 인코딩) | 쪽 번호(p.1~p.3) 위치와 한글 텍스트가 추출됨 | 3쪽 추출, p.2 에 E101 | ✅ |
| test_extractors.py | `test_pdf_cross_check_page_count_with_pypdf` | 샘플 PDF 를 외부 라이브러리(pypdf, 개발용)로도 열어 쪽수 비교 | 같은 3쪽 — 샘플이 유효한 PDF 이고 추출기의 쪽 구분이 정확함 | 예상 결과와 일치 | ✅ |
| test_extractors.py | `test_pdf_encodings[False-False]` | 손으로 만든 PDF — 비압축/Flate 압축 × 1바이트 문자열/2바이트 코드 16진 문자열 | 모든 조합에서 쪽별 텍스트 추출 | 예상 결과와 일치 | ✅ |
| test_extractors.py | `test_pdf_encodings[False-True]` | 손으로 만든 PDF — 비압축/Flate 압축 × 1바이트 문자열/2바이트 코드 16진 문자열 | 모든 조합에서 쪽별 텍스트 추출 | 예상 결과와 일치 | ✅ |
| test_extractors.py | `test_pdf_encodings[True-False]` | 손으로 만든 PDF — 비압축/Flate 압축 × 1바이트 문자열/2바이트 코드 16진 문자열 | 모든 조합에서 쪽별 텍스트 추출 | 예상 결과와 일치 | ✅ |
| test_extractors.py | `test_pdf_encodings[True-True]` | 손으로 만든 PDF — 비압축/Flate 압축 × 1바이트 문자열/2바이트 코드 16진 문자열 | 모든 조합에서 쪽별 텍스트 추출 | 예상 결과와 일치 | ✅ |
| test_extractors.py | `test_xlsx_inline_strings_and_numeric_header` | sharedStrings 없이 inlineStr 만 쓰는 xlsx, 첫 행이 숫자인 시트 | 오류 없이 읽고, 숫자 첫 행은 머리글로 보지 않음(값만 이어 붙임) | 예상 결과와 일치 | ✅ |
| test_extractors.py | `test_col_letters` | 열 번호 1, 26, 27, 702 | A, Z, AA, ZZ | 예상 결과와 일치 | ✅ |
| test_extractors.py | `test_corrupt_and_unsupported_files_raise_invalid` | 손상 xlsx/pptx, 빈 시트 xlsx, PDF 아님, 텍스트 없는 PDF, 암호화 PDF, DTD 포함 XML | 모두 InvalidDocumentError(본문 내용 없는 사유)로 처리되어 앱이 중단되지 않음 | 손상/빈/비PDF/스캔/암호화/DTD 모두 InvalidDocumentError | ✅ |
| test_extractors.py | `test_zip_member_limit` | 구성요소 3000개짜리 압축 파일(압축 폭탄 유형) | 크기/개수 제한으로 거부 | 예상 결과와 일치 | ✅ |
| test_search.py | `test_expected_documents_found` | 정상 업무 질문 8개 (계리평가팀 사용자) | 8개 모두 기대 문서가 상위 3위 이내 (기준: 5개 중 4개 이상 → 상위 기준 충족) | 8/8 적중 (GW-001:O, SF-002:O, GW-002:O, SF-003:O, BS-002:O, BS-003:O, SF-001:O, BS-001:O) | ✅ |
| test_search.py | `test_synonyms_find_rafm_faq[RAFM \uc2e4\ud589 \uc624\ub958]` | 'RAFM 실행 오류' / '모델 에러' / '모델 실행 실패' / '모델 장애 대응' | 유사 표현이라도 RAFM 오류 대응 FAQ(GW-001)가 1위 | 1위=GW-001 | ✅ |
| test_search.py | `test_synonyms_find_rafm_faq[\ubaa8\ub378 \uc5d0\ub7ec]` | 'RAFM 실행 오류' / '모델 에러' / '모델 실행 실패' / '모델 장애 대응' | 유사 표현이라도 RAFM 오류 대응 FAQ(GW-001)가 1위 | 1위=GW-001 | ✅ |
| test_search.py | `test_synonyms_find_rafm_faq[\ubaa8\ub378 \uc2e4\ud589 \uc2e4\ud328]` | 'RAFM 실행 오류' / '모델 에러' / '모델 실행 실패' / '모델 장애 대응' | 유사 표현이라도 RAFM 오류 대응 FAQ(GW-001)가 1위 | 1위=GW-001 | ✅ |
| test_search.py | `test_synonyms_find_rafm_faq[\ubaa8\ub378 \uc7a5\uc560 \ub300\uc751]` | 'RAFM 실행 오류' / '모델 에러' / '모델 실행 실패' / '모델 장애 대응' | 유사 표현이라도 RAFM 오류 대응 FAQ(GW-001)가 1위 | 1위=GW-001 | ✅ |
| test_search.py | `test_alias_normalization` | 'IFRS 17', '보험계약집단' 표기 | 'IFRS17', 'GoC' 문서와 동일하게 검색됨 | 예상 결과와 일치 | ✅ |
| test_search.py | `test_results_sorted_and_capped` | 여러 문서에 걸치는 질문 | 점수 내림차순 정렬, 최대 5건, 각 결과에 점수/원본 위치/원문 문단 포함 | 예상 결과와 일치 | ✅ |
| test_search.py | `test_category_and_source_filters` | 분류 필터(RAFM) 또는 저장소 필터(업무시스템)를 적용한 검색 | 결과가 해당 분류/저장소 문서로만 구성 | 예상 결과와 일치 | ✅ |
| test_search.py | `test_results_span_multiple_sources` | 'RAFM 모델 실행 오류' (계리평가팀) | 그룹웨어·업무시스템 등 서로 다른 저장소의 문서가 한 결과 목록에 함께 표시 | ['공유폴더', '그룹웨어', '업무시스템'] | ✅ |
| test_search.py | `test_no_results_for_unrelated_question` | 문서에 없는 주제(휴가 규정의 육아휴직 수당) | status=no_results, 결과 0건, 임의 생성 없음 | 예상 결과와 일치 | ✅ |
| test_search.py | `test_empty_query_is_handled` | 빈 검색어 / 공백 / 의미 없는 기호 | 예외 없이 안내 상태(empty_query / no_results) | 예상 결과와 일치 | ✅ |
| test_search.py | `test_particles_and_endings_stripped` | '오류가 발생하면', '결산은' | 조사/어미 제거 후 핵심 용어('오류', '발생', '결산')만 개념으로 추출 | 예상 결과와 일치 | ✅ |
| test_search.py | `test_no_documents_indexed_status` | 색인을 한 번도 만들지 않은 상태에서 검색 | 'no_sources' 안내 (연결된 저장소/색인 없음), 예외 없음 | 예상 결과와 일치 | ✅ |
| test_search.py | `test_no_connectors_status` | 연결된 저장소(Connector)가 0개 | 동기화/검색 모두 예외 없이 'no_sources' | 예상 결과와 일치 | ✅ |
| test_search_ux.py | `test_locations_per_file_type` | 'E101 오류 조치' 검색(계리평가팀, 결과 20건까지) | PDF 는 'p.2', Excel 은 "시트 '오류내역' · 셀 …", PowerPoint 는 '슬라이드 3', Markdown 은 '줄 N' | {'SF-102': ["시트 '오류내역' · 셀 A2:C2", "시트 '오류내역' · 셀 A1:C1"], 'SF-103': ['슬라이드 3'], 'SF-101': ['p.2', 'p.3']} | ✅ |
| test_search_ux.py | `test_result_fields_for_list_display` | 검색 결과 한 건 | 문서명, 파일 형식, 수정일, 원본 UNC 경로(공유폴더), 공유 이름이 모두 채워져 있음 | 예상 결과와 일치 | ✅ |
| test_search_ux.py | `test_file_type_filter` | 문서 유형 필터 pdf / xlsx+pptx / 존재하지 않는 조합 | 선택한 유형의 문서만 반환, 해당 없으면 no_results | [('SF-102', 'xlsx'), ('SF-103', 'pptx')] | ✅ |
| test_search_ux.py | `test_location_filter_multi_share` | 위치 필터 — 계리평가 공유만 / 계리평가+재무팀 공유 / 그룹웨어만 | 선택한 위치(공유)의 문서만 결과에 포함 (다중 경로 검색) | ['계리평가 공유', '재무팀 공유'] | ✅ |
| test_search_ux.py | `test_modified_date_filter` | 수정일 범위 — 2026-10-06 이후 / 2026-09-01~2026-09-30 / 날짜 객체와 문자열 모두 | 경계일 포함으로 범위 안의 문서만 반환 | [('BS-001', '2026-10-06'), ('BS-002', '2026-10-09'), ('SF-101', '2026-10-08'), ('SF-102', '2026-10-06'), ('SF-201', '2026-10-12')] | ✅ |
| test_search_ux.py | `test_filters_combine` | 유형 + 위치 + 분류 + 수정일 필터를 동시에 적용 | 모든 조건을 동시에 만족하는 문서만 반환 | 예상 결과와 일치 | ✅ |
| test_search_ux.py | `test_scope_name_vs_body` | 검색 대상 — 파일명만 / 본문만 / 통합 | 파일명만: 본문에만 있는 용어(E101)는 결과 없음, 파일명 용어('체크시트')는 문서 발견(본문 위치 없음). | 파일명만 '체크시트' → ['SF-201'] | ✅ |
| test_search_ux.py | `test_filename_search_hits_file_name_not_only_title` | 제목에는 없고 파일명에만 있는 단어('킥오프_자료' → '킥오프')가 아닌 파일명 토큰으로 검색 | 'GoC_단위_변동분석_매뉴얼' 처럼 밑줄로 이어진 파일명 형태로 검색해도 문서를 찾음 | 예상 결과와 일치 | ✅ |
| test_search_ux.py | `test_sorting[modified-<lambda>]` | 정렬 기준 수정일/파일명/경로/형식, 오름·내림차순 | 결과 전체가 해당 기준으로 단조 정렬됨 | 예상 결과와 일치 | ✅ |
| test_search_ux.py | `test_sorting[name-<lambda>]` | 정렬 기준 수정일/파일명/경로/형식, 오름·내림차순 | 결과 전체가 해당 기준으로 단조 정렬됨 | 예상 결과와 일치 | ✅ |
| test_search_ux.py | `test_sorting[path-<lambda>]` | 정렬 기준 수정일/파일명/경로/형식, 오름·내림차순 | 결과 전체가 해당 기준으로 단조 정렬됨 | 예상 결과와 일치 | ✅ |
| test_search_ux.py | `test_sorting[type-<lambda>]` | 정렬 기준 수정일/파일명/경로/형식, 오름·내림차순 | 결과 전체가 해당 기준으로 단조 정렬됨 | 예상 결과와 일치 | ✅ |
| test_search_ux.py | `test_relevance_sort_default_and_reverse` | 관련도 정렬 내림/오름 | 내림차순은 점수 큰 순, 오름차순은 반대 | 예상 결과와 일치 | ✅ |
| test_search_ux.py | `test_top_k_choices` | 결과 수 5(기본) / 10 / 20 / 1000 | 기본 5건, 일치 문서가 더 있으면 10건까지 확장, 상한 20 초과 요청은 20 으로 제한, total_matched 는 전체 일치 수 | 기본 5건 / 10 → 10건 / 총 일치 11건 | ✅ |
| test_search_ux.py | `test_filter_changes_do_not_reuse_stale_cache` | 같은 검색어를 필터만 바꿔 연속 검색 | 캐시가 필터별로 분리되어 각각 올바른 결과 반환 | 예상 결과와 일치 | ✅ |
| test_search_ux.py | `test_new_documents_respect_acl` | 재무팀 사용자가 PDF/Excel/PPT 문서가 있는 주제를 검색, 계리 전용 Excel(SF-102)·관리자 문서 포함 | 재무팀 권한 문서(SF-101/103/201/202 등)만 나오고 SF-102·SF-004 는 어떤 필터/정렬에서도 노출되지 않음 | 재무팀 결과 문서 합집합: ['BS-002', 'SF-001', 'SF-101', 'SF-103'] | ✅ |
| test_search_ux.py | `test_matching_chunks_navigation_and_acl` | 문서 안 일치 위치 목록 조회(미리보기의 이전/다음 이동 근거) | 문서 순서의 일치 위치 목록(PDF p.2 포함), 검색어 없음/비인가 사용자는 빈 목록 | [(1, 'p.2', 2.0), (2, 'p.3', 0.75)] | ✅ |
| test_search_ux.py | `test_acl_revoke_on_pdf_via_sidecar` | PDF 의 메타데이터 파일에서 재무팀 권한을 회수하고 색인 갱신 | 권한변경으로 감지, 재무팀 검색·원문 미리보기에서 사라짐 (바이너리 문서에도 권한 재검증 적용) | 예상 결과와 일치 | ✅ |
| test_search_ux.py | `test_xlsx_add_modify_delete_sync` | 공유폴더에 Excel 추가 → 셀 값 수정 → 파일 삭제 후 각각 색인 갱신 | 추가 시 셀 위치와 함께 검색, 수정 시 최신 값으로 교체, 삭제 시 결과에서 제거 | 시트 '집계' · 셀 A2:B2 | ✅ |
| test_search_ux.py | `test_old_index_schema_is_rebuilt` | 이전 버전 스키마의 색인 DB 파일 위에서 앱 시작 | 오류 없이 새 스키마로 재생성(파생 데이터이므로 비우고 재색인), 이후 정상 색인·검색 | 예상 결과와 일치 | ✅ |
| test_search_ux.py | `test_snippet_centers_on_match_and_highlights_safely` | 긴 본문 중간에 검색어가 있는 텍스트, HTML 태그가 섞인 텍스트 | 일치 위치 주변만 '…'과 함께 발췌되고 일치 단어가 강조되며 HTML 은 이스케이프됨 | … 앞부분 앞부분 앞부분 앞부분 앞부분 앞부분 앞부분 앞부분 앞부분 RAFM 실행 오류가  | ✅ |
| test_search_ux.py | `test_location_key_and_folder_of` | 공유폴더/그룹웨어 문서의 위치 키, UNC 경로의 상위 폴더 계산 | 공유는 'shared_folder:표시이름', 그 외는 저장소 키, 상위 폴더 경로는 파일명 제외 | 예상 결과와 일치 | ✅ |
| test_search_ux.py | `test_unc_path_html_keeps_double_backslash` | UNC 경로를 마크다운 안의 HTML 로 출력 | 역슬래시가 문자 참조로 바뀌어 마크다운 이스케이프에 의해 줄어들지 않고, HTML 특수문자는 이스케이프됨 | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_valid_unc[\\\\fs01\\\uacf5\uc720]` | 올바른 UNC 경로(호스트명/IP/하위폴더/앞뒤 공백·끝 역슬래시) | 통과하고 정규화(공백·끝 역슬래시 제거) | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_valid_unc[\\\\fs-01.example.invalid\\\uacc4\ub9ac\ud3c9\uac00\\\ud558\uc704\\\ud3f4\ub354]` | 올바른 UNC 경로(호스트명/IP/하위폴더/앞뒤 공백·끝 역슬래시) | 통과하고 정규화(공백·끝 역슬래시 제거) | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_valid_unc[\\\\10.0.0.5\\share]` | 올바른 UNC 경로(호스트명/IP/하위폴더/앞뒤 공백·끝 역슬래시) | 통과하고 정규화(공백·끝 역슬래시 제거) | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_valid_unc[  \\\\fs01\\\uacf5\uc720\\  ]` | 올바른 UNC 경로(호스트명/IP/하위폴더/앞뒤 공백·끝 역슬래시) | 통과하고 정규화(공백·끝 역슬래시 제거) | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_invalid_unc[]` | 잘못된 UNC(드라이브 경로, 슬래시, 공유명 없음, 금지문자, 호스트 없음) | ShareError | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_invalid_unc[C:\\temp]` | 잘못된 UNC(드라이브 경로, 슬래시, 공유명 없음, 금지문자, 호스트 없음) | ShareError | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_invalid_unc[//fs01/share]` | 잘못된 UNC(드라이브 경로, 슬래시, 공유명 없음, 금지문자, 호스트 없음) | ShareError | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_invalid_unc[\\\\fs01]` | 잘못된 UNC(드라이브 경로, 슬래시, 공유명 없음, 금지문자, 호스트 없음) | ShareError | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_invalid_unc[\\\\fs01\\]` | 잘못된 UNC(드라이브 경로, 슬래시, 공유명 없음, 금지문자, 호스트 없음) | ShareError | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_invalid_unc[\\fs01\\share]` | 잘못된 UNC(드라이브 경로, 슬래시, 공유명 없음, 금지문자, 호스트 없음) | ShareError | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_invalid_unc[\\\\fs01\\\uacf5\uc720\\..\\x<y]` | 잘못된 UNC(드라이브 경로, 슬래시, 공유명 없음, 금지문자, 호스트 없음) | ShareError | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_invalid_unc[\\\\fs 01\\\uacf5\uc720]` | 잘못된 UNC(드라이브 경로, 슬래시, 공유명 없음, 금지문자, 호스트 없음) | ShareError | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_invalid_unc[\\\\\\share]` | 잘못된 UNC(드라이브 경로, 슬래시, 공유명 없음, 금지문자, 호스트 없음) | ShareError | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_unc_path_built_from_share_root` | 등록부 기반 공유폴더 Connector 로 PDF 문서 수집 | 원본 위치가 '공유 UNC 루트 + 하위 경로(역슬래시)' 형태의 UNC 경로 | \\fs-actu01.example.invalid\계리평가\결산검증\결산_내부통제_점검보고서.pdf | ✅ |
| test_shares.py | `test_multi_share_collects_all_and_labels` | 등록된 공유 3곳(계리평가/재무팀/관리자 전용) | 공유별로 문서가 수집되고 share 표시명이 채워짐, 총 15건 색인 | {'계리평가 공유': 6, '관리자 전용': 1, '재무팀 공유': 2} | ✅ |
| test_shares.py | `test_register_new_share_indexes_its_documents` | 새 가상 폴더를 UNC 경로로 등록한 뒤 색인 갱신 | 새 공유의 문서가 검색되고 원본 위치가 새 UNC 경로, 같은 문서 ID 중복 등록 없음 | \\fs-new01.example.invalid\신계약\점검메모.md | ✅ |
| test_shares.py | `test_unregister_and_disable_remove_documents` | 공유 등록 해제 / 검색 사용 안 함 설정 후 색인 갱신 | 해당 공유 문서가 삭제로 처리되어 검색에서 사라지고, 다시 켜면 복원됨 | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_register_validation_errors` | 빈 이름, 잘못된 UNC, 경로 탈출(../, 하위경로), 없는 폴더, 중복 이름/UNC/폴더 | 모두 ShareError 로 거부되고 등록부는 변경되지 않음 | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_missing_share_folder_isolated` | 등록된 공유 중 하나의 가상 폴더가 사라짐(경로 없음) | 그 공유만 '접근할 수 없습니다'로 보고되고 나머지 공유 문서는 정상 수집 | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_binary_without_or_with_bad_sidecar` | 메타데이터(.meta.json) 없는 PDF, 형식이 깨진 메타데이터, 손상된 xlsx | 각각 사유와 함께 invalid 로 보고되고 다른 문서는 계속 수집 | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_legacy_single_root_mode_still_works` | 등록부 없이 루트 폴더 하나로 만든 기존 방식 Connector | 하위 폴더 전체를 읽고 기본 UNC 표시명이 사용됨 (기존 공유폴더 연결 기능 유지) | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_symlink_outside_share_is_ignored` | 공유 폴더 안에 공유 밖 파일을 가리키는 심볼릭 링크 | 공유 밖 파일은 읽지 않음(경로 탈출 방지) | 예상 결과와 일치 | ✅ |
| test_shares.py | `test_registry_file_roundtrip_keeps_notice` | 공유 등록 후 등록부 파일 확인 | JSON 형식 유지, 안내(notice)문 보존, 한글 그대로 저장 | 예상 결과와 일치 | ✅ |
| test_sync.py | `test_initial_sync_indexes_all` | 최초 색인 | 15건 색인(공유 9/그룹웨어 3/업무 3), 세 저장소 상태 ok | 15건 색인, 3개 저장소 ok | ✅ |
| test_sync.py | `test_resync_without_changes_is_noop` | 변경 없이 색인 갱신 재실행 | 변경 0건, 중복 등록 없음(문서 수 15 유지), 색인 세대 번호 불변 | 예상 결과와 일치 | ✅ |
| test_sync.py | `test_new_document_reflected` | 공유폴더에 신규 문서 추가 후 색인 갱신 | 갱신 전 검색 불가 → 갱신 후 검색됨, 신규 1건 감지 | 신규 반영 후 1위=SF-100 | ✅ |
| test_sync.py | `test_modified_document_reflected` | GW-002(공지) 본문 수정(마감일 변경) 후 색인 갱신 | 수정 1건 감지, 최신 문구로 검색되고 이전 문구는 더 이상 검색되지 않음 | 수정 후 검색 1위=GW-002 | ✅ |
| test_sync.py | `test_version_change_detected` | BS-003 버전 2.0 → 2.1 변경 후 색인 갱신 | 버전변경으로 분류, 색인의 버전 값 갱신, 문서 중복 없음 | 예상 결과와 일치 | ✅ |
| test_sync.py | `test_deleted_document_removed` | GW-001 게시글 삭제 후 색인 갱신 | 삭제 1건 감지, 검색/원문 열람/색인 조각에서 모두 제거, 이전 캐시 결과도 제거 | 삭제 후 결과=['BS-001', 'SF-103', 'GW-003', 'SF-102', 'BS-003'] | ✅ |
| test_sync.py | `test_file_becomes_invalid_is_removed` | 색인된 파일이 손상(메타데이터 삭제)된 뒤 색인 갱신 | 오래된 내용이 남지 않도록 색인에서 제거, 형식 오류로 보고 | 예상 결과와 일치 | ✅ |
| test_sync.py | `test_duplicate_id_across_sources` | 그룹웨어에 이미 공유폴더가 사용 중인 ID(SF-001)로 게시글 추가 | 먼저 등록된 공유폴더 문서 유지, 그룹웨어 문서는 중복으로 제외(중복 등록 없음) | 중복=['SF-001'] | ✅ |
| test_sync.py | `test_connector_failure_isolated_and_reported` | 그룹웨어 Connector 가 연결 오류를 내는 상태에서 색인·검색 | 다른 두 저장소는 정상 색인/검색, 그룹웨어는 error 로 표시되어 검색 제외, 결과에 '검색 못한 저장소'로 안내 | 결과 저장소=['공유폴더', '업무시스템'], 제외=['그룹웨어'] | ✅ |
| test_sync.py | `test_connector_crash_message_not_leaked` | Connector 가 예기치 않은 예외(내부정보 포함)를 던짐 | 앱은 중단되지 않고 오류 유형만 보고, 예외 메시지의 민감 문자열은 보고서에 없음 | 예상 결과와 일치 | ✅ |
| test_sync.py | `test_source_recovery` | 저장소 오류 후 복구되어 다시 색인 갱신 | 상태가 ok 로 돌아오고 해당 저장소 문서가 다시 검색됨 | 예상 결과와 일치 | ✅ |
| test_sync.py | `test_all_sources_down` | 세 저장소 모두 접근 불가 | 예외 없이 no_sources 안내, 모든 저장소가 '검색 못한 저장소'로 표시 | 예상 결과와 일치 | ✅ |
