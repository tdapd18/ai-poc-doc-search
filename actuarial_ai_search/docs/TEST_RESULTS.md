# 자동 테스트 결과 (pytest)

- 전체 69건 중 통과 69건 / 실패 0건
- 데이터는 모두 가상 더미데이터이며 외부 네트워크·실제 LLM 호출은 없습니다 (LLM 관련은 Mock 구현으로 검증).

| 파일 | 테스트 | 입력조건 | 예상 결과 | 실제 결과 | 통과 |
|---|---|---|---|---|---|
| test_access_control.py | `test_visible_documents_differ_by_user` | 계리평가팀/재무팀/관리자 가상 사용자별 접근 가능 문서 | 계리 9건, 재무 3건(SF-001, GW-002, BS-002), 관리자 10건 | actuary=9, finance=3, admin=10 | ✅ |
| test_access_control.py | `test_unauthorized_documents_not_searchable` | 재무팀 사용자가 RAFM FAQ·GoC 매뉴얼·관리자 전용 문서 주제를 검색 | 권한 없는 문서(GW-001, SF-002, SF-004, BS-001 ...)가 결과에 전혀 없음 | 재무팀 결과 문서: ['BS-002', 'GW-002', 'SF-001'] | ✅ |
| test_access_control.py | `test_admin_only_doc_hidden_from_actuary` | '예외 승인 내역' 검색 (계리 vs 관리자) | 계리평가팀은 SF-004 미노출, 관리자는 SF-004 노출 | 예상 결과와 일치 | ✅ |
| test_access_control.py | `test_no_side_channel_counts` | 계리 전용 문서와 겹치는 질문을 재무팀(접근 가능 문서 3건)이 검색, 비인가 문서 전용 주제도 검색 | 일치 건수·결과가 재무팀 접근 가능 문서(최대 3건)만으로 계산되고, 메시지에 '권한/제외' 등 비인가 문서 존재를 암시하는 표현 없음 | GoC 변동 분석 매뉴얼 → status=ok, total_matched=2, 결과=['SF-001', 'BS-002'] | ✅ |
| test_access_control.py | `test_unauthorized_preview_blocked` | 재무팀 사용자가 GW-001/SF-004 원문 열기 시도, 존재하지 않는 ID 열기 | 모두 None (존재/권한 여부를 구분하지 않음), 권한자는 열람 가능 | 예상 결과와 일치 | ✅ |
| test_access_control.py | `test_default_deny_rules` | ACL 이 비어 있는 문서, 알 수 없는 사용자, None 사용자 | 모두 거부 (기본 거부 정책) | 예상 결과와 일치 | ✅ |
| test_access_control.py | `test_unknown_user_gets_denied_search` | 등록되지 않은 사용자/None 으로 검색 | status=denied, 결과 없음 (비정상 종료 없음) | 예상 결과와 일치 | ✅ |
| test_access_control.py | `test_acl_grant_reflected_after_sync` | SF-002(GoC 매뉴얼)의 allowed_groups 에 finance 추가 후 색인 갱신 | 갱신 전에는 재무팀 검색 불가, 갱신 후 검색/열람 가능, 권한변경 1건 감지 | acl_changed=['SF-002'] | ✅ |
| test_access_control.py | `test_acl_revoke_blocks_cache_and_history` | 재무팀이 접근 가능한 SF-001 로 검색·이력 생성 → SF-001 권한을 계리팀 전용으로 회수 → 색인 갱신 | 같은 질문 재검색(캐시 포함)에서 SF-001 미노출, 원문 열람 불가, 이전 답변 이력은 숨김 처리 | 회수 후 재무팀 결과=['BS-002', 'GW-002'], from_cache=False | ✅ |
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
| test_app_smoke.py | `test_app_starts_with_three_sources` | 웹앱 첫 실행 | 예외 없이 기동, 자동 색인으로 계리평가팀 기준 9건 표시 | 앱 기동·자동 색인 확인 | ✅ |
| test_app_smoke.py | `test_search_select_source_and_preview` | 추천 질문 클릭 → 근거 문서 보기 클릭 | 검색 결과와 근거 문서가 표시되고, 오른쪽 패널에 문서명/버전/원본 위치가 나타남 | 검색→출처 선택→원문/원본 위치 표시 확인 | ✅ |
| test_app_smoke.py | `test_empty_query_shows_warning` | 검색어 없이 검색 버튼 | 경고 안내, 앱 중단 없음 | 예상 결과와 일치 | ✅ |
| test_app_smoke.py | `test_user_switch_changes_visible_documents` | 가상 사용자를 재무팀으로 전환 | 접근 가능 문서 수 9 → 3, 계리 전용 문서 제목이 목록에서 사라짐 | 재무팀 3건 표시 | ✅ |
| test_app_smoke.py | `test_refresh_button_and_revocation_hides_old_answer` | 재무팀 검색 후 SF-001 권한 회수 → 색인 갱신 버튼 | 갱신 후 결과·근거 패널에서 SF-001 내용이 사라지고, 이전 답변 이력은 숨김 안내가 표시됨 | 권한 회수 후 결과/원문/이력에서 SF-001 노출 없음 | ✅ |
| test_connectors.py | `test_three_connectors_collect_documents` | 가상 저장소 3개(공유폴더/그룹웨어/업무시스템) 수집 | 공유폴더 4, 그룹웨어 3, 업무시스템 3건 — 총 10건(최소 9건 충족), 형식 오류 없음 | {'공유폴더': 4, '그룹웨어': 3, '업무시스템': 3} | ✅ |
| test_connectors.py | `test_common_schema_has_all_metadata` | 세 Connector 수집 결과 | 모든 문서가 공통 메타데이터(ID/문서명/시스템/분류/버전/작성·수정일/부서/위치/본문)를 가짐 | 예상 결과와 일치 | ✅ |
| test_connectors.py | `test_doc_ids_unique_across_sources` | 세 저장소 전체 문서 | 문서 ID 중복 없음 | 예상 결과와 일치 | ✅ |
| test_connectors.py | `test_shared_folder_recursion_and_change_detection` | 하위 폴더 포함 공유폴더 스캔 후 파일 추가/수정/삭제 | 하위 폴더 파일 탐색, 신규/변경/삭제 파일이 각각 감지됨 | {'new': ['가정관리/새문서.txt'], 'changed': ['분석매뉴얼/GoC_단위_변동분석_매뉴얼.md'], 'removed': ['결산검증/IFRS17_결산검증가이드.md']} | ✅ |
| test_connectors.py | `test_groupware_keeps_url_and_attachments` | 그룹웨어 게시글 수집 | 게시글 고유 ID(GW-xxx)와 가상 원본 URL, 첨부파일 정보를 보존 | 예상 결과와 일치 | ✅ |
| test_connectors.py | `test_business_system_preserves_id_and_screen_path` | 업무시스템 레코드 수집 | 업무시스템 ID(BS-xxx)와 원본 화면 위치 보존, 구조화 표가 텍스트 표로 변환됨 | 예상 결과와 일치 | ✅ |
| test_connectors.py | `test_invalid_documents_are_reported_not_crashing` | 잘못된 형식 문서 5종(메타데이터 없음/필수 누락/날짜 오류/깨진 JSON/비UTF-8) | 예외 없이 invalid 목록에 사유만 기록, 정상 문서는 계속 수집, 사유에 본문 내용이 없음 | 공유폴더 invalid=['bad1.md', 'bad2.md', 'bad3.md'], 그룹웨어 invalid=['broken.json'] | ✅ |
| test_connectors.py | `test_duplicate_id_in_same_source` | 같은 문서 ID(SF-001)를 가진 두 번째 파일 추가 | 하나만 채택하고 중복 목록/오류 항목에 기록 | 예상 결과와 일치 | ✅ |
| test_connectors.py | `test_missing_root_raises_connector_error` | 존재하지 않는 저장소 경로 | ConnectorError (저장소 단위 오류로 상위에서 격리 처리) | 예상 결과와 일치 | ✅ |
| test_connectors.py | `test_business_record_with_bad_table_is_invalid` | 표의 행 길이가 컬럼 수와 다른 업무시스템 레코드 | 해당 레코드만 invalid, 나머지 정상 | 예상 결과와 일치 | ✅ |
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
| test_sync.py | `test_initial_sync_indexes_all` | 최초 색인 | 10건 색인(공유 4/그룹웨어 3/업무 3), 세 저장소 상태 ok | 10건 색인, 3개 저장소 ok | ✅ |
| test_sync.py | `test_resync_without_changes_is_noop` | 변경 없이 색인 갱신 재실행 | 변경 0건, 중복 등록 없음(문서 수 10 유지), 색인 세대 번호 불변 | 예상 결과와 일치 | ✅ |
| test_sync.py | `test_new_document_reflected` | 공유폴더에 신규 문서 추가 후 색인 갱신 | 갱신 전 검색 불가 → 갱신 후 검색됨, 신규 1건 감지 | 신규 반영 후 1위=SF-100 | ✅ |
| test_sync.py | `test_modified_document_reflected` | GW-002(공지) 본문 수정(마감일 변경) 후 색인 갱신 | 수정 1건 감지, 최신 문구로 검색되고 이전 문구는 더 이상 검색되지 않음 | 수정 후 검색 1위=GW-002 | ✅ |
| test_sync.py | `test_version_change_detected` | BS-003 버전 2.0 → 2.1 변경 후 색인 갱신 | 버전변경으로 분류, 색인의 버전 값 갱신, 문서 중복 없음 | 예상 결과와 일치 | ✅ |
| test_sync.py | `test_deleted_document_removed` | GW-001 게시글 삭제 후 색인 갱신 | 삭제 1건 감지, 검색/원문 열람/색인 조각에서 모두 제거, 이전 캐시 결과도 제거 | 삭제 후 결과=['BS-001', 'GW-003', 'BS-003', 'SF-001', 'GW-002'] | ✅ |
| test_sync.py | `test_file_becomes_invalid_is_removed` | 색인된 파일이 손상(메타데이터 삭제)된 뒤 색인 갱신 | 오래된 내용이 남지 않도록 색인에서 제거, 형식 오류로 보고 | 예상 결과와 일치 | ✅ |
| test_sync.py | `test_duplicate_id_across_sources` | 그룹웨어에 이미 공유폴더가 사용 중인 ID(SF-001)로 게시글 추가 | 먼저 등록된 공유폴더 문서 유지, 그룹웨어 문서는 중복으로 제외(중복 등록 없음) | 중복=['SF-001'] | ✅ |
| test_sync.py | `test_connector_failure_isolated_and_reported` | 그룹웨어 Connector 가 연결 오류를 내는 상태에서 색인·검색 | 다른 두 저장소는 정상 색인/검색, 그룹웨어는 error 로 표시되어 검색 제외, 결과에 '검색 못한 저장소'로 안내 | 결과 저장소=['공유폴더', '업무시스템'], 제외=['그룹웨어'] | ✅ |
| test_sync.py | `test_connector_crash_message_not_leaked` | Connector 가 예기치 않은 예외(내부정보 포함)를 던짐 | 앱은 중단되지 않고 오류 유형만 보고, 예외 메시지의 민감 문자열은 보고서에 없음 | 예상 결과와 일치 | ✅ |
| test_sync.py | `test_source_recovery` | 저장소 오류 후 복구되어 다시 색인 갱신 | 상태가 ok 로 돌아오고 해당 저장소 문서가 다시 검색됨 | 예상 결과와 일치 | ✅ |
| test_sync.py | `test_all_sources_down` | 세 저장소 모두 접근 불가 | 예외 없이 no_sources 안내, 모든 저장소가 '검색 못한 저장소'로 표시 | 예상 결과와 일치 | ✅ |
