# 자동 테스트 결과 (pytest)

- 전체 247건 중 통과 247건 / 실패 0건
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
| test_extractors_v2.py | `test_docx_headings_tables_pages_footnotes` | 제목·문단·페이지 나눔·표·변경 추적 삭제문·각주가 있는 DOCX | 제목별로 문단이 묶이고 '문단 a–b · 약 N쪽' 위치, 표는 '표 N · 행 R' + 머리글 라벨, 삭제된 문장·각주 처리, 문서 제목 속성 추출 | ['문단 1–3 · 약 1–2쪽', '표 1 · 행 1 · 약 2쪽', '표 1 · 행 2 · 약 2쪽', '표 1 · 행 3 · 약 2쪽', '각주 1'] | ✅ |
| test_extractors_v2.py | `test_docx_explicit_page_breaks_when_no_rendered_info` | lastRenderedPageBreak 없이 명시적 쪽 나눔만 있는 DOCX | 명시적 쪽 나눔으로 '약 2쪽'을 추정 | 예상 결과와 일치 | ✅ |
| test_extractors_v2.py | `test_docx_errors` | 구형 OLE 시그니처의 .docx(암호화/구형), 손상 zip, 본문 없는 docx | 각각 암호/구형·손상·텍스트 없음 오류(InvalidDocumentError) | 예상 결과와 일치 | ✅ |
| test_extractors_v2.py | `test_csv_encodings[utf-8-\xef\xbb\xbf]` | 같은 한글 CSV 를 UTF-8 BOM / CP949(한국어 Excel 기본) / UTF-8 로 저장 | 모두 올바른 한글로 읽히고 '머리글: 값' 형태, 위치는 '행 N' | utf-8: ('CSV', '행 2', '모델: 장기보장 모델 \| 실행횟수: 12 \| 판정: 적합') | ✅ |
| test_extractors_v2.py | `test_csv_encodings[cp949-]` | 같은 한글 CSV 를 UTF-8 BOM / CP949(한국어 Excel 기본) / UTF-8 로 저장 | 모두 올바른 한글로 읽히고 '머리글: 값' 형태, 위치는 '행 N' | cp949: ('CSV', '행 2', '모델: 장기보장 모델 \| 실행횟수: 12 \| 판정: 적합') | ✅ |
| test_extractors_v2.py | `test_csv_encodings[utf-8-]` | 같은 한글 CSV 를 UTF-8 BOM / CP949(한국어 Excel 기본) / UTF-8 로 저장 | 모두 올바른 한글로 읽히고 '머리글: 값' 형태, 위치는 '행 N' | utf-8: ('CSV', '행 2', '모델: 장기보장 모델 \| 실행횟수: 12 \| 판정: 적합') | ✅ |
| test_extractors_v2.py | `test_csv_delimiters_grouping_and_errors` | 세미콜론·탭 구분 CSV, 2500행 CSV, 빈 CSV | 구분자 자동 판별, 2000행 초과 시 10행씩 묶어 '행 a–b', 빈 파일은 오류 | 예상 결과와 일치 | ✅ |
| test_extractors_v2.py | `test_decode_text_detection` | UTF-8, UTF-8 BOM, UTF-16, CP949, 판별 불가 바이트 | 각 인코딩을 판별하고 판별 불가는 대체 문자로 처리(예외 없음) | 예상 결과와 일치 | ✅ |
| test_extractors_v2.py | `test_xlsx_dates_percent_formulas_hidden_phonetic` | 날짜 서식 셀(시리얼 값), 퍼센트, 수식 캐시 값, 오류 값, 후리가나가 있는 공유 문자열, 숨김 시트 | 날짜는 ISO 로, 퍼센트는 %로, 수식 값은 결과값으로, 오류 값·후리가나·숨김 시트는 색인하지 않고 숨김 시트는 경고로 보고 | 항목: 결산 \| 기준일: 2026-10-14 \| 변동률: 5.23% \| 합계: 3 | ✅ |
| test_extractors_v2.py | `test_xlsx_custom_date_1904_and_missing_cell_refs` | 1904 날짜 체계 통합 문서, 셀 주소(r) 속성이 없는 행 | 1904 기준으로 날짜 변환, 주소가 없으면 순서대로 A,B,C 부여 | 예상 결과와 일치 | ✅ |
| test_extractors_v2.py | `test_pptx_hidden_footer_break_smartart_table_notes` | 숨김 슬라이드, 꼬리말·슬라이드 번호 자리표시자, 줄바꿈, SmartArt 텍스트, 표, 발표자 노트 | 숨김 슬라이드는 '(숨김)' 표기, 꼬리말·번호는 제외, 줄바꿈 유지, SmartArt·표·노트 포함 | ['슬라이드 1', '슬라이드 2 (숨김)', '슬라이드 3'] | ✅ |
| test_extractors_v2.py | `test_pdf_tounicode_objstm_nested_pages[False-False-False]` | Identity-H 글꼴 + ToUnicode(한글) PDF 를 객체 스트림 유무 × 중첩 페이지 트리 × ASCII85+Flate 조합으로 생성 | 모든 조합에서 쪽 순서대로 한글 텍스트가 줄 단위로 복원됨(Word/Excel 'PDF로 저장' 구조) | objstm=False nested=False a85=False OK | ✅ |
| test_extractors_v2.py | `test_pdf_tounicode_objstm_nested_pages[False-False-True]` | Identity-H 글꼴 + ToUnicode(한글) PDF 를 객체 스트림 유무 × 중첩 페이지 트리 × ASCII85+Flate 조합으로 생성 | 모든 조합에서 쪽 순서대로 한글 텍스트가 줄 단위로 복원됨(Word/Excel 'PDF로 저장' 구조) | objstm=True nested=False a85=False OK | ✅ |
| test_extractors_v2.py | `test_pdf_tounicode_objstm_nested_pages[False-True-False]` | Identity-H 글꼴 + ToUnicode(한글) PDF 를 객체 스트림 유무 × 중첩 페이지 트리 × ASCII85+Flate 조합으로 생성 | 모든 조합에서 쪽 순서대로 한글 텍스트가 줄 단위로 복원됨(Word/Excel 'PDF로 저장' 구조) | objstm=False nested=True a85=False OK | ✅ |
| test_extractors_v2.py | `test_pdf_tounicode_objstm_nested_pages[False-True-True]` | Identity-H 글꼴 + ToUnicode(한글) PDF 를 객체 스트림 유무 × 중첩 페이지 트리 × ASCII85+Flate 조합으로 생성 | 모든 조합에서 쪽 순서대로 한글 텍스트가 줄 단위로 복원됨(Word/Excel 'PDF로 저장' 구조) | objstm=True nested=True a85=False OK | ✅ |
| test_extractors_v2.py | `test_pdf_tounicode_objstm_nested_pages[True-False-False]` | Identity-H 글꼴 + ToUnicode(한글) PDF 를 객체 스트림 유무 × 중첩 페이지 트리 × ASCII85+Flate 조합으로 생성 | 모든 조합에서 쪽 순서대로 한글 텍스트가 줄 단위로 복원됨(Word/Excel 'PDF로 저장' 구조) | objstm=False nested=False a85=True OK | ✅ |
| test_extractors_v2.py | `test_pdf_tounicode_objstm_nested_pages[True-False-True]` | Identity-H 글꼴 + ToUnicode(한글) PDF 를 객체 스트림 유무 × 중첩 페이지 트리 × ASCII85+Flate 조합으로 생성 | 모든 조합에서 쪽 순서대로 한글 텍스트가 줄 단위로 복원됨(Word/Excel 'PDF로 저장' 구조) | objstm=True nested=False a85=True OK | ✅ |
| test_extractors_v2.py | `test_pdf_tounicode_objstm_nested_pages[True-True-False]` | Identity-H 글꼴 + ToUnicode(한글) PDF 를 객체 스트림 유무 × 중첩 페이지 트리 × ASCII85+Flate 조합으로 생성 | 모든 조합에서 쪽 순서대로 한글 텍스트가 줄 단위로 복원됨(Word/Excel 'PDF로 저장' 구조) | objstm=False nested=True a85=True OK | ✅ |
| test_extractors_v2.py | `test_pdf_tounicode_objstm_nested_pages[True-True-True]` | Identity-H 글꼴 + ToUnicode(한글) PDF 를 객체 스트림 유무 × 중첩 페이지 트리 × ASCII85+Flate 조합으로 생성 | 모든 조합에서 쪽 순서대로 한글 텍스트가 줄 단위로 복원됨(Word/Excel 'PDF로 저장' 구조) | objstm=True nested=True a85=True OK | ✅ |
| test_extractors_v2.py | `test_pdf_kerning_inserts_space` | TJ 배열의 큰 음수 커닝(단어 간격 표현)이 있는 PDF | 커닝 위치에 공백이 복원됨('결산검' + '증보고서' → '결산검 증보고서') | 예상 결과와 일치 | ✅ |
| test_extractors_v2.py | `test_pdf_cid_font_without_tounicode_is_reported_not_garbled` | ToUnicode 가 없는 Identity-H(CID) 글꼴 PDF | 잘못된 글자를 만들지 않고 '텍스트를 추출할 수 없습니다 (스캔본이거나 …)'로 보고 | 예상 결과와 일치 | ✅ |
| test_extractors_v2.py | `test_pdf_real_producer_embedded_font_with_tounicode` | reportlab(실제 PDF 생성 라이브러리)으로 TrueType 글꼴을 임베딩해 만든 PDF (Identity-H + ToUnicode) | 표준 라이브러리 추출기가 한자·영문 텍스트를 복원하고, 외부 라이브러리(pypdf)가 읽은 텍스트와 일치 | 決算検証 report E101 / 第二行 CSM 5% | ✅ |
| test_extractors_v2.py | `test_pdf_flate_literal_latin_and_tj_arrays` | 이전 형식(Helvetica 리터럴 문자열) PDF 가 새 추출기에서도 동작 | 기존 추출 결과 유지(회귀 방지) | 예상 결과와 일치 | ✅ |
| test_fs.py | `test_unc_string_helpers` | UNC 문자열 정규화/결합/상대경로/상위/키/확장 경로 변환 | 중복·끝 구분자 정리, 대소문자 무시 비교, 루트 밖 상대화 거부, 긴 경로 접두사 변환 | \\?\UNC\srv\sh\x | ✅ |
| test_fs.py | `test_mapped_fs_is_case_insensitive_like_windows` | 대소문자가 다른 경로 / 한글·공백 폴더로 목록·상태·읽기 | Windows 처럼 대소문자와 무관하게 같은 파일을 찾음 | 예상 결과와 일치 | ✅ |
| test_fs.py | `test_access_denied_semantics` | 폴더 목록 거부 / 파일 읽기 거부 주입 | 목록 거부는 scandir 실패, 읽기 거부는 목록에는 보이나 열기·읽기는 FsAccessDenied (NTFS 에서 흔한 상태) | 목록 거부/읽기 거부/복구 확인 | ✅ |
| test_fs.py | `test_offline_lock_vanish_and_not_found` | 공유 오프라인 / 파일 잠금 / 목록 후 사라짐 / 없는 경로·루트 밖 경로·`..` | 각각 FsUnavailable / FsUnavailable / FsNotFound / FsNotFound | 예상 결과와 일치 | ✅ |
| test_fs.py | `test_counters_distinguish_open_check_from_body_read` | check_open 과 read_bytes 호출 | opens 와 reads 가 따로 기록되어 '내용을 읽었는지'를 검증할 수 있음 | 예상 결과와 일치 | ✅ |
| test_fs.py | `test_symlink_reported_as_link` | 폴더를 가리키는 링크(접합 점 모사) | is_link=True, 디렉터리로 취급하지 않음(순회 루프 방지의 근거) | 예상 결과와 일치 | ✅ |
| test_fs.py | `test_oserror_classification` | Windows winerror(5,2,32,53,1231)와 errno 값 | 거부 / 없음 / 사용 중(불가) / 네트워크(불가) 로 분류, 메시지에 경로 없음 | winerror/errno 분류 확인 | ✅ |
| test_fs.py | `test_local_fs_on_plain_paths` | LocalFS(OS 직접)로 로컬 폴더 읽기 / 없는 경로 | 목록·상태·읽기·열기 확인 동작, 없는 경로는 FsNotFound (확장 경로 변환은 Windows 에서만 사용) | 예상 결과와 일치 | ✅ |
| test_fs.py | `test_identity_from_env` | USERDOMAIN/USERNAME 환경값, 값이 없는 환경 | 'DOMAIN\user' 형태, 비교키는 대소문자 무시, 계정을 알 수 없으면 UNKNOWN (임의 계정 가장 금지) | 예상 결과와 일치 | ✅ |
| test_fs.py | `test_config_defaults_are_safe_and_roundtrip` | 설정 파일이 없을 때 / 저장 후 재로드 | 기본은 데모 모드·메타데이터 전용·승인 없음, 저장 값 보존, 파일 권한 600(posix) | 예상 결과와 일치 | ✅ |
| test_fs.py | `test_full_text_requires_approval_record` | 승인 확인 없이/승인자 없이 본문 모드 전환 시도, 정상 승인 후 전환, 다시 메타 전용 | 승인 없으면 ConfigError, 승인 시 기록(승인자·일시·문구) 저장, 메타 전용으로 돌아가면 승인 해제, 모드 변경은 True 반환(색인 초기화 신호) | 승인 기록 필수, 해제 시 승인도 해제 | ✅ |
| test_fs.py | `test_tampered_config_cannot_enable_full_text_without_record` | 설정 파일에 index_mode=full_text 만 직접 써넣고 승인 기록은 없음 | 로드 시 안전한 기본값(metadata_only)으로 되돌림 | 예상 결과와 일치 | ✅ |
| test_fs.py | `test_audit_log_has_no_paths_or_content` | 경로 문자열·긴 문자열이 포함된 감사 이벤트 기록 | 경로 구분자가 든 값은 기록하지 않고 긴 문자열은 잘라서 기록, 건수/상태는 기록 | 예상 결과와 일치 | ✅ |
| test_real_app.py | `test_first_run_opens_setup_with_safe_defaults` | 실제 모드 첫 실행(등록된 공유 없음) | 초기 설정 화면이 열리고, 현재 Windows 계정 표시, 기본 보안 모드는 메타데이터 전용, 가상 사용자 선택은 없음 | 첫 실행: 설정 화면, 기본 메타데이터 전용 | ✅ |
| test_real_app.py | `test_register_validation_messages` | 잘못된 UNC·관리자 공유·정상 경로·중복 경로를 차례로 등록 | 오류는 안내 문구로 표시되고 정상 경로만 등록됨 | 예상 결과와 일치 | ✅ |
| test_real_app.py | `test_connection_test_then_index_in_metadata_only` | 공유 등록 → 연결 테스트 → 색인 생성(메타데이터 전용) | 연결 테스트 전에는 색인 버튼이 비활성, 테스트 성공 후 활성화, 색인 중 파일 내용 읽기 0회, 완료 후 문서 수 표시 | 본문 읽기 0회, 열기 확인 28회 | ✅ |
| test_real_app.py | `test_connection_failures_show_guidance_and_block_indexing` | 오프라인 / 접근 거부 공유에서 연결 테스트 | 원인별 조치 안내가 표시되고 색인 생성은 막힘 | 예상 결과와 일치 | ✅ |
| test_real_app.py | `test_search_page_in_metadata_mode` | 색인 후 검색 화면에서 파일명으로 검색, 본문 용어로 검색 | 메타데이터 전용 배너, Windows 계정 표시, 결과에 UNC 경로와 '본문 미색인' 배지, 본문 용어는 결과 없음 | 메타 전용: 파일명 검색 성공, 본문 문구 검색은 결과 없음 | ✅ |
| test_real_app.py | `test_full_text_switch_requires_acknowledgement_and_resets` | 설정 화면에서 본문 검색 선택 → 확인 없이 적용 → 확인+승인 참조 입력 후 적용 → 색인 재생성 → 본문 검색 | 확인 없으면 오류, 적용 시 기존 색인 삭제 안내, 재색인 후 본문과 표/행 위치로 검색됨 | 승인 기록 후 본문 색인, 표 행 위치로 검색 | ✅ |
| test_real_app.py | `test_permission_revocation_visible_in_ui_without_resync` | 본문 색인 후 한 문서의 권한 회수 → 같은 검색 재실행(색인 갱신 없음) → 미리보기 열기 | 결과에서 즉시 사라지고 미리보기는 열 수 없음 안내 | 예상 결과와 일치 | ✅ |
| test_real_app.py | `test_delete_index_button` | 색인 생성 후 설정 화면에서 확인 체크 후 '색인 삭제' | 확인 전에는 비활성, 확인 후 로컬 색인이 모두 삭제되고 단계 표시가 초기화 | 예상 결과와 일치 | ✅ |
| test_real_app.py | `test_unregister_share_and_disable` | 등록된 공유를 '색인에 사용' 해제 / 등록 해제 | 사용 안 함이면 테스트·색인 대상에서 빠지고, 등록 해제하면 목록에서 사라짐 | 예상 결과와 일치 | ✅ |
| test_real_app.py | `test_first_screen_hides_revoked_file_without_resync` | 본문 색인 후 한 파일의 권한 회수·다른 파일 삭제(색인 갱신 없음) → 앱 첫 화면(검색 전) | 문서 목록·경로·접근 가능 문서 수·유형별 건수·필터 선택지에 회수/삭제 파일이 나타나지 않음 | 접근 가능 문서 19 → 17, 회수·삭제 파일명 비노출 | ✅ |
| test_real_mode.py | `test_register_unc_validation` | 실제 UNC 등록 — 관리자 공유(C$), 장치 경로, 드라이브 경로, 슬래시 경로, 하위/상위 중복, 경로 구분자가 든 제외 패턴, 정상 등록 | 위험·잘못된 입력은 ShareError 로 거부되고 정상 등록은 kind=unc 로 저장됨 | 관리자 공유·장치 경로·중복·겹침 거부 확인 | ✅ |
| test_real_mode.py | `test_metadata_only_never_reads_file_content` | 기본 설정(메타데이터 전용)으로 합성 공유를 색인 | 파일 내용을 읽은 횟수 0(reads=[]), 권한 확인용 열기만 수행, 본문 조각·본문 텍스트가 색인 DB 어디에도 없음(고유 문구 미존재) | 문서 18건 색인, 본문 읽기 0회, 열기 확인 18회 | ✅ |
| test_real_mode.py | `test_metadata_only_search_by_name_path_and_body_notice` | 메타데이터 전용에서 파일명·폴더명·확장자로 검색, 본문 용어로 검색, 본문만 범위로 검색 | 파일명·폴더 경로로는 찾고, 본문 용어는 못 찾으며, 본문만 범위는 결과 없음 + 본문 미색인 문서 수 안내 | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_full_text_requires_approval_and_switch_resets_index` | 승인 없이 본문 모드 전환 시도 → 승인 후 전환 → 본문 색인 → 다시 메타데이터 전용으로 전환 | 승인 없으면 거부, 전환 시 색인 초기화(문서 0건), 본문 모드에서는 본문이 색인되고, 되돌리면 본문(고유 문구)이 DB 파일에서도 사라짐 | 본문 모드 전환/복귀 시 색인 초기화, 복귀 후 DB 에 본문 문구 없음 | ✅ |
| test_real_mode.py | `test_auto_index_without_meta_json_and_metadata_derivation` | .meta.json 없이 합성 업무문서를 본문 모드로 색인 | 문서 ID(F-…, 경로 기반), 제목(문서 속성/파일명), 버전(파일명 패턴), 분류(키워드), 부서(상위 폴더), 수정일(파일 시각)이 자동 도출되고 형식별 위치가 기록됨 | 13건: GoC_변동_2026-09.csv, IFRS17 결산 검증 가이드_v2.1.docx, RAFM_오류대응_FAQ.md, front.md, 결산 [최종] #1 & 검토.txt, 깊은문서.txt, 내부통제 점검보고서.pd | ✅ |
| test_real_mode.py | `test_cp949_text_and_csv_are_decoded` | CP949 로 저장된 한글 TXT/CSV (한국어 Windows 기본 저장 형식) | 글자가 깨지지 않고 본문 검색이 됨 | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_front_matter_and_sidecar_override_auto_metadata` | 머리말(--- 메타데이터)이 있는 MD, 옆에 .meta.json 이 있는 DOCX | 명시된 메타데이터(doc_id MD-777, 제목·분류)가 자동 도출값보다 우선 (.meta.json 은 선택 사항) | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_excluded_unsupported_legacy_and_error_files_are_reported` | 잠금(~$)·Thumbs.db·desktop.ini·숨김·이미지·구형(.doc/.xls)·암호화 DOCX·손상 XLSX·0바이트 TXT 가 섞인 공유 | 임시/시스템/숨김 파일은 제외, 이미지는 미지원 집계, 구형은 파일명 검색만(메타 수준), 암호화·손상·빈 파일은 사유와 함께 보고(앱은 계속 동작) | invalid=['깨진 집계.xlsx', '빈 메모.txt', '암호화된 문서.docx'], skipped={'구형/미지원 형식 — 파일명 검색만': 2, '지원하지 않는 형식': 1} | ✅ |
| test_real_mode.py | `test_large_file_falls_back_to_metadata_level` | 크기 한도(1MB)를 넘는 CSV | 본문은 읽지 않고(읽기 호출 없음) 파일명 검색만 가능한 메타데이터 수준으로 색인하고 사유를 보고 | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_same_names_special_chars_long_paths_and_case_insensitive_ids` | 같은 이름 다른 폴더, 특수문자 이름, 6단계 긴 폴더명(경로 260자 초과), 대소문자만 다른 경로 | 모두 별도 문서로 색인(중복 오류 없음), 경로 대소문자만 다르면 같은 문서 ID | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_incremental_sync_rereads_only_changed_but_rechecks_permission` | 변경 없이 색인 갱신을 다시 실행 → 파일 1개 수정 후 다시 실행 | 변경 없는 파일은 본문을 다시 읽지 않고(reads 불변) 권한 확인용 열기만 다시 수행, 수정한 파일만 다시 읽어 갱신(수정 1건) | 재색인 시 정상 문서 중 본문을 다시 읽은 것은 수정된 1개뿐(오류 파일 3건은 매번 재확인) | ✅ |
| test_real_mode.py | `test_rename_is_delete_plus_add` | 파일 이름 변경 | 이전 경로 문서는 삭제, 새 경로 문서는 신규(경로 기반 ID 이므로) | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_progress_callback_and_audit_log_without_names` | 진행률 콜백을 주고 색인 → 감사 로그 확인 | 마지막 이벤트가 done 이고 파일 수가 보고되며, 감사 로그에는 건수만 있고 파일명·경로·본문은 없음 | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_unreadable_files_and_folders_are_not_indexed` | 파일 읽기 거부(기밀 폴더)와 폴더 목록 거부(목록거부 폴더)가 있는 공유 | 두 곳의 문서는 색인되지 않고 '읽기 권한 없음 N건'으로 건수만 보고(파일명 미노출), 나머지는 정상 색인 | 색인 14건, 권한 없음 2건 집계 | ✅ |
| test_real_mode.py | `test_revoked_permission_is_hidden_immediately_everywhere` | 색인 후 DOCX 의 읽기 권한이 회수됨(색인 갱신 전) — 검색·캐시·미리보기·원문 위치·AI 근거·이전 답변 | 색인 갱신을 기다리지 않고 모든 곳에서 즉시 숨김. 캐시 적중 결과도 재검증으로 폐기 | 검색/캐시/미리보기/위치/AI 근거/이전 답변에서 즉시 숨김 | ✅ |
| test_real_mode.py | `test_revoked_then_synced_removes_index_and_restored_comes_back` | 권한 회수 → 색인 갱신 → 권한 복구 → 색인 갱신 | 갱신 시 색인·조각이 삭제되고(권한 없음 집계), 복구 후 갱신하면 다시 색인됨 | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_permission_revoked_on_unchanged_file_is_detected_by_recheck` | 파일 내용·수정시각은 그대로이고 권한만 회수(ACL 변경은 mtime 을 바꾸지 않음) 후 색인 갱신 | 증분 수집이 '변경 없음'으로 건너뛰지 않고 권한을 재확인해 색인에서 제거 | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_denied_subfolder_removes_its_documents_failclosed` | 색인 후 하위 폴더('데이터') 목록 권한이 회수됨 | 그 폴더 아래 문서(CSV·TXT)가 색인에서 제거되고 다른 폴더 문서는 유지 | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_other_windows_account_gets_its_own_clean_index` | 같은 홈 폴더를 다른 Windows 계정으로 열기 / 대소문자만 다른 같은 계정으로 열기 | 다른 계정이면 색인을 폐기(본문 문구도 DB 에서 제거), 같은 계정(대소문자 무시)이면 유지 | 다른 계정 접근 시 색인 폐기 | ✅ |
| test_real_mode.py | `test_identity_gate` | 다른 사용자 신원으로 검색/열기 시도 | 현재 Windows 계정이 아니면 어떤 문서도 접근 불가(denied) | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_deleted_file_hidden_immediately_and_secure_deleted_after_sync` | 파일 삭제 → (갱신 전) 검색 → 색인 갱신 → 색인 파일 확인 | 갱신 전에도 조회에서 숨김, 갱신 후 색인·조각 삭제, 색인 DB 파일 바이트에 본문 고유 문구가 남지 않음(secure_delete) | 삭제 후 DB 바이트에 본문 문구 없음 | ✅ |
| test_real_mode.py | `test_modified_file_shows_stale_until_resync` | 색인 후 파일 수정(갱신 전) → 갱신 | 갱신 전에는 '원본이 변경됨(stale)' 표시, 갱신 후에는 표시 없음 | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_share_offline_hides_results_but_keeps_index_and_recovers` | 공유 전체가 오프라인(VPN 단절) 상태에서 검색·색인 갱신 → 복구 | 검색 결과는 숨김, 색인 갱신은 해당 공유를 '연결할 수 없음'으로 보고하고 기존 색인을 지우지 않음, 복구 후 재색인 없이 다시 검색됨 | 오프라인 중 색인 16건 유지, 복구 후 즉시 검색 | ✅ |
| test_real_mode.py | `test_subfolder_transient_error_retains_only_that_subtree` | 하위 폴더('결산')만 일시적으로 연결 불가인 상태에서 색인 갱신 | 그 폴더 아래 문서는 삭제하지 않고 유지(조회 시 숨김), 나머지는 정상 처리 | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_locked_file_is_retained_not_deleted` | 색인된 파일이 다른 프로그램에 잠김(공유 위반) 상태에서 수정 후 색인 갱신 | 기존 색인을 지우지 않고 재시도 대상으로 보고, 조회에서는 숨김, 잠금 해제 후 갱신하면 최신 내용 반영 | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_file_changed_while_reading_is_skipped_and_old_index_kept` | 파일을 읽는 도중 내용이 바뀜(읽기 직후 수정 시각 불일치) | 불완전한 내용을 색인하지 않고 기존 색인을 유지하며 재시도 대상으로 보고, 안정되면 반영 | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_file_cap_makes_scan_partial_and_does_not_delete` | 파일 수 한도를 낮춰 부분 수집이 된 색인 갱신 | 확인하지 못한 문서를 삭제하지 않고 유지하며 부분 수집 경고를 보고 | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_share_specific_exclude_patterns` | 공유 단위 제외 패턴('구형', 'A') | 해당 이름의 폴더 아래 문서는 색인하지 않음 | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_disabled_or_removed_share_removes_documents` | 공유를 사용 안 함으로 바꾸거나 등록 해제한 뒤 색인 갱신 | 그 공유의 문서가 색인에서 모두 삭제됨 (삭제된 내용은 DB 에 남지 않음) | 예상 결과와 일치 | ✅ |
| test_real_mode.py | `test_index_file_is_private_on_posix` | 개인 색인 DB / 설정 파일 생성 | 본인만 읽고 쓸 수 있는 권한(600). Windows 에서는 사용자 프로필 폴더의 기본 ACL 에 의존(문서화) | 예상 결과와 일치 | ✅ |
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
| test_search_scale.py | `test_prefilter_gives_identical_results_demo[all]` | 데모 데이터에서 15개 질의(동의어·별칭·일반어·특수문자·결과 없음)를 3개 검색 대상으로 실행 | 후보 추출 방식의 결과(문서 순서·점수·일치 위치·일치 건수)가 전체 조각 순회 기준 구현과 완전히 같음 | scope=all: 질의 15개, 기준 구현과 순위·점수·위치 일치 (일치 문서 합계 78) | ✅ |
| test_search_scale.py | `test_prefilter_gives_identical_results_demo[name]` | 데모 데이터에서 15개 질의(동의어·별칭·일반어·특수문자·결과 없음)를 3개 검색 대상으로 실행 | 후보 추출 방식의 결과(문서 순서·점수·일치 위치·일치 건수)가 전체 조각 순회 기준 구현과 완전히 같음 | scope=name: 질의 15개, 기준 구현과 순위·점수·위치 일치 (일치 문서 합계 26) | ✅ |
| test_search_scale.py | `test_prefilter_gives_identical_results_demo[body]` | 데모 데이터에서 15개 질의(동의어·별칭·일반어·특수문자·결과 없음)를 3개 검색 대상으로 실행 | 후보 추출 방식의 결과(문서 순서·점수·일치 위치·일치 건수)가 전체 조각 순회 기준 구현과 완전히 같음 | scope=body: 질의 15개, 기준 구현과 순위·점수·위치 일치 (일치 문서 합계 76) | ✅ |
| test_search_scale.py | `test_prefilter_gives_identical_results_real_share` | 실제 모드 합성 공유(DOCX/XLSX/PPTX/PDF/CSV, 메타데이터 수준 문서 포함)에서 같은 비교 | 기준 구현과 완전히 같은 결과 | 예상 결과와 일치 | ✅ |
| test_search_scale.py | `test_prefilter_scores_only_candidate_chunks` | 'E101' 한 단어 검색 시 점수 계산에 투입되는 조각 수 | 전체 조각 수보다 훨씬 적은 후보 조각만 점수 계산(속도 개선의 근거) | 예상 결과와 일치 | ✅ |
| test_search_scale.py | `test_normalization_signature_recomputed_when_dictionary_changes` | 별칭 사전이 바뀐 뒤 같은 색인을 새 사전의 엔진으로 열기 | 저장된 정규화 텍스트가 자동으로 다시 계산되어, 새 사전 기준으로 검색됨 ('IFRS 17' ↔ 'ifrs17') | 예상 결과와 일치 | ✅ |
| test_search_scale.py | `test_candidate_chunks_escape_sql_wildcards` | 질의 용어에 %, _, 역슬래시가 포함된 경우의 후보 추출 | 와일드카드로 해석되지 않고 문자 그대로만 일치 (예: 'a_b' 는 'axb' 와 일치하지 않음) | 예상 결과와 일치 | ✅ |
| test_search_scale.py | `test_list_documents_does_not_load_bodies` | 문서 목록 조회 / 단건 조회 / include_body 옵션 | 목록에는 본문이 없고(검색마다 전체 본문을 읽지 않음), 단건 조회와 옵션 지정 시에는 본문 포함 | 예상 결과와 일치 | ✅ |
| test_search_scale.py | `test_benchmark_smoke_small` | 합성 문서 1,500건(조각 5개)을 색인하고 선택적/광범위/결과 없음 질의 실행 | 정상 동작하고 아주 넉넉한 시간 안에 응답(성능 회귀 감시용 — 실제 성능은 tools/benchmark_search.py 로 측정) | 예상 결과와 일치 | ✅ |
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
| test_security_hardening.py | `test_list_hides_revoked_file_everywhere_before_resync` | 색인 후 DOCX 읽기 권한 회수(색인 갱신 없음) — 문서 목록·접근 가능 문서 수·유형별/위치별 건수·필터 선택지·경로 | 회수된 파일명·경로가 목록에 없고 건수가 1 줄며, 해당 유형 건수가 줄어들고 필터 선택지가 실제 접근 가능한 값만 남음 | 16건 → 15건 → 13건 | ✅ |
| test_security_hardening.py | `test_list_with_filters_is_verified_and_stale_index_not_modified` | 분류·유형·위치·날짜 필터를 건 목록 조회 중 권한 회수 | 필터를 건 조회도 동일하게 재검증하고, 조회가 색인을 바꾸지 않음(색인 세대 유지) | 예상 결과와 일치 | ✅ |
| test_security_hardening.py | `test_virtual_demo_mode_list_unchanged` | 데모(가상 사용자) 모드의 문서 목록 | 기존 ACL 결과와 동일(재검증 정책이 데모 ACL 결과를 바꾸지 않음) | 13건 동일 | ✅ |
| test_security_hardening.py | `test_network_outage_then_recovery` | 공유 전체 오프라인 → 목록·검색·미리보기 → 복구 | 오프라인 중에는 목록·경로·건수·결과·미리보기 모두 비어 있고(캐시 포함), 복구 후 색인 갱신 없이 다시 보이며 '없음' 결과가 캐시에 남지 않음 | 오프라인 0건 → 복구 16건 | ✅ |
| test_security_hardening.py | `test_permission_revoked_then_restored` | 권한 회수 → 확인 → 권한 복구 → 확인 | 회수 중에는 어디에도 안 보이고, 복구하면 색인 갱신 없이 다시 표시됨. 회수 중 색인 갱신 시에는 색인에서 제거되고 복구 후 재색인으로 돌아옴 | 예상 결과와 일치 | ✅ |
| test_security_hardening.py | `test_deleted_file_disappears_from_list_before_resync` | 파일 삭제(색인 갱신 없음) → 목록 → 색인 갱신 | 갱신 전에도 목록·건수에서 제외, 갱신 후 색인에서도 삭제 | 예상 결과와 일치 | ✅ |
| test_security_hardening.py | `test_modified_file_never_shows_old_paragraphs` | 본문 색인 후 원본 수정(색인 갱신 없음) — 검색 결과 문단, 미리보기, 일치 위치, AI 근거, 이전 답변 | '원본 변경됨' 표시와 함께 과거 문단 본문이 어디에도 노출되지 않음. 색인 갱신 후에는 새 내용만 표시됨 | 수정 후 stale: 문단·미리보기·근거·이전 답변 비노출, 갱신 후 새 내용 | ✅ |
| test_security_hardening.py | `test_vanished_mid_session_does_not_leak_name_or_path` | 목록 조회 중 파일이 사라짐(vanish) | 해당 문서가 목록에서 제외됨 | 예상 결과와 일치 | ✅ |
| test_security_hardening.py | `test_home_dir_is_owner_only` | 실제 모드 서비스 생성 | 색인 폴더 0700, index.db 0600 | 예상 결과와 일치 | ✅ |
| test_security_hardening.py | `test_no_journal_or_temp_files_left_after_sync_and_reset` | 본문 색인 → 갱신 → 색인 삭제 | 색인 폴더에 -journal/-wal/-shm/임시 파일이 남지 않고, 삭제 후 DB 바이트에 본문 문구가 없음 | 저널·임시 파일 없음, reset 후 본문 문구 없음 | ✅ |
| test_security_hardening.py | `test_residue_purge_overwrites_backups_and_keeps_live_files` | 색인 폴더에 index.db.bak, 색인 복사본, 임시 파일이 남아 있음 → 서비스 기동 | 기동 시 잔존 파일이 덮어쓰기 후 삭제되고 index.db·config·shares.json 은 유지됨 | 잔존 3개 삭제, 라이브 파일 유지 | ✅ |
| test_security_hardening.py | `test_wipe_file_overwrites_before_unlink` | 본문이 든 파일을 wipe_file | 파일이 삭제되고 없는 파일도 오류 없이 처리 | 예상 결과와 일치 | ✅ |
| test_security_hardening.py | `test_corrupt_index_is_discarded_and_rebuilt` | 비정상 종료로 index.db 가 손상됨 → 서비스 기동 | 손상 파일을 폐기하고 빈 색인으로 시작, 다시 색인 가능 | 예상 결과와 일치 | ✅ |
| test_security_hardening.py | `test_sync_folder_warning` | 색인 폴더가 OneDrive 폴더 아래 | 클라우드 동기화 경고 문구가 나옴 | 예상 결과와 일치 | ✅ |
| test_security_hardening.py | `test_db_pragmas_do_not_use_disk_temp` | 파일 DB 연결 | secure_delete=ON, temp_store=MEMORY, journal_mode=MEMORY | 예상 결과와 일치 | ✅ |
| test_setup_check.py | `test_successful_check_reports_stats_without_reading_content` | 정상 합성 공유에서 연결 테스트 | 성공(ok), 형식별 파일 수·미지원·구형 집계, 권한 표본 읽기 가능, 파일 내용 읽기 호출 0회 | ok=True 색인대상≈19 형식={'txt': 7, 'xlsx': 2, 'docx': 3, 'md': 2, 'csv': 1, 'pdf': 1, 'pptx': 1} 표본 9/9 | ✅ |
| test_setup_check.py | `test_exclusions_applied_in_check` | 기본 제외 패턴(~$, Thumbs.db, desktop.ini, 숨김)과 공유 단위 제외 패턴 | 점검 통계에서도 제외 대상은 집계되지 않음 | 예상 결과와 일치 | ✅ |
| test_setup_check.py | `test_error_codes_with_guidance` | 잘못된 경로 형식 / 계정 접근 거부 / 없는 경로 / 오프라인 | invalid_path / denied / not_found / unavailable 로 구분되고 사용자용 메시지가 있음 | 예상 결과와 일치 | ✅ |
| test_setup_check.py | `test_denied_subfolders_and_sample_permission_warnings` | 하위 폴더 목록 거부, 일부 파일 읽기 거부 | 접근 불가 폴더 수·표본 거부가 경고로 보고되고 점검은 계속 성공 | 예상 결과와 일치 | ✅ |
| test_setup_check.py | `test_scan_limit_and_time_budget_mark_truncated` | 점검 항목 한도를 낮춤 / 시간 한도를 초과하는 시계 | truncated=True 와 추정치 안내 경고 | 예상 결과와 일치 | ✅ |
| test_setup_check.py | `test_oversize_files_warned` | 크기 한도(1MB)를 넘는 파일 | 경고로 보고(파일명 검색만 가능) | 예상 결과와 일치 | ✅ |
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
