# Tasks: LINE 日語學習助教 Bot

**Feature ID**: `001-line-jp-learning`  
**Date**: 2026-01-27  
**Prerequisites**: spec.md (required), plan.md (required)  
**Version**: 1.1.0

---

## Task Format

```
- [ ] [ID] [Priority] [Risk] [Story?] Description with file path
  - **DoD**: Definition of Done
```

**欄位說明**:

| Marker | Description |
|--------|-------------|
| `[P1/P2/P3]` | 優先級（P1 最高，P3 最低） |
| `[Risk: L/M/H]` | Low / Medium / High 風險等級 |
| `[US#]` | 所屬 User Story（e.g., US1, US2） |
| `[P]` | 可平行執行（不同檔案、無相依） |
| **DoD** | Definition of Done（驗收條件） |

**Risk 分類指南**:

| Risk | 定義 |
|------|------|
| L | 標準 CRUD、config、文件更新 |
| M | 涉及外部 API 或複雜邏輯 |
| H | LLM 整合、prompt 設計、效能關鍵路徑 |

---

## Phase 1: Setup

**Purpose**: Project initialization and basic structure

- [x] T001 [P1] [Risk: L] Create project structure per plan.md in src/, tests/, alembic/
  - **DoD**: 目錄結構存在，符合 plan.md Project Structure 定義

- [x] T002 [P1] [Risk: L] Initialize Python project with pyproject.toml and requirements.txt
  - **DoD**: `pip install -e .` 成功執行，無錯誤

- [x] T003 [P1] [Risk: L] [P] Configure linting (ruff) and formatting (black) in pyproject.toml
  - **DoD**: `ruff check .` 與 `black --check .` 可執行

- [x] T004 [P1] [Risk: L] [P] Create .env.example with all required environment variables
  - **DoD**: 包含 DATABASE_URL, LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, ANTHROPIC_API_KEY, OPENAI_API_KEY

- [x] T005 [P1] [Risk: M] [P] Setup Supabase project and obtain connection string
  - **DoD**: 可透過 connection string 連線至 Supabase PostgreSQL

- [x] T006 [P1] [Risk: M] [P] Create LINE Messaging API channel and obtain credentials
  - **DoD**: 取得 channel_secret 與 channel_access_token，webhook URL 可設定

**Checkpoint**: Project skeleton ready, can run `pip install -e .`

---

## Phase 2: Foundation (Blocking)

**Purpose**: Core infrastructure that MUST be complete before user story work

**CRITICAL**: No user story work can begin until this phase is complete

### Database and Models

- [x] T007 [P1] [Risk: L] Create src/config.py with Pydantic Settings for environment management
  - **DoD**: Config 可從 .env 讀取所有必要變數；missing var 時拋出 ValidationError

- [x] T008 [P1] [Risk: M] Setup SQLAlchemy async engine in src/database.py
  - **DoD**: `async with get_session()` 可取得 AsyncSession；連線 Supabase 成功

- [x] T009 [P1] [Risk: L] [P] Create RawMessage model in src/models/raw_message.py
  - **DoD**: Model 定義符合 plan.md Data Model；可 import 無錯誤

- [x] T010 [P1] [Risk: L] [P] Create Document model in src/models/document.py
  - **DoD**: Model 定義符合 plan.md Data Model；FK 關聯 raw_messages 正確

- [x] T011 [P1] [Risk: L] [P] Create Item model in src/models/item.py
  - **DoD**: Model 定義符合 plan.md Data Model；unique constraint on (user_id, item_type, key)

- [x] T012 [P1] [Risk: L] [P] Create PracticeLog model in src/models/practice_log.py
  - **DoD**: Model 定義符合 plan.md Data Model；FK 關聯 items 正確

- [x] T013 [P1] [Risk: M] Create Alembic migration for all tables in alembic/versions/
  - **DoD**: `alembic upgrade head` 成功建立 4 張表；`alembic downgrade -1` 可回滾

- [ ] T014 [P1] [Risk: M] Run migration and verify tables exist in Supabase
  - **DoD**: 透過 Supabase Dashboard 或 psql 確認 raw_messages, documents, items, practice_logs 存在

### Infrastructure

- [x] T015 [P1] [Risk: L] [P] Create base repository class in src/repositories/base.py
  - **DoD**: BaseRepository 提供 get_by_id, create, update, soft_delete 方法

- [x] T016 [P1] [Risk: L] [P] Implement RawMessageRepository in src/repositories/raw_message_repo.py
  - **DoD**: 可 create/get raw_message；get_latest_by_user 方法可用

- [x] T017 [P1] [Risk: L] [P] Implement DocumentRepository in src/repositories/document_repo.py
  - **DoD**: 可 create/get document；get_deferred_by_user 回傳 parse_status=deferred 的文件

- [x] T018 [P1] [Risk: L] [P] Implement ItemRepository in src/repositories/item_repo.py
  - **DoD**: 可 create/get/upsert item；upsert 依 (user_id, item_type, key) 正確更新

- [x] T019 [P1] [Risk: L] [P] Implement PracticeLogRepository in src/repositories/practice_log_repo.py
  - **DoD**: 可 create/get practice_log；get_by_item 回傳該 item 的練習紀錄

- [x] T020 [P1] [Risk: M] [P] Create Japanese text normalizer in src/lib/normalizer.py
  - **DoD**: normalize() 支援全半形轉換、假名正規化；單元測試涵蓋 10+ 案例

- [x] T021 [P1] [Risk: H] [P] Create LLM client wrapper with fallback in src/lib/llm_client.py
  - **DoD**: Anthropic 呼叫成功回傳；模擬 timeout/error 時 fallback 至 OpenAI；單元測試覆蓋雙路徑

- [x] T022 [P1] [Risk: M] [P] Create LINE client wrapper in src/lib/line_client.py
  - **DoD**: reply_message(reply_token, text) 可送出回覆；signature 驗證方法可用

- [x] T023 [P1] [Risk: L] Setup FastAPI app with health endpoint in src/main.py
  - **DoD**: GET /health 回傳 {"status": "ok"}；uvicorn 可啟動

- [x] T024 [P1] [Risk: M] Create error handling middleware in src/api/middleware.py
  - **DoD**: 未處理例外回傳 500 JSON 格式錯誤；request_id 記錄於 log

**Checkpoint**: Foundation ready — can connect to DB, call LLM, receive LINE webhook

---

## Phase 3: User Story 1 - 素材入庫 (P1) MVP

**Goal**: 使用者可在 LINE 貼入日文素材並保存

**Spec Reference**: US1 in spec.md — FR-001, FR-002

**Independent Test**: Send "入庫" command via LINE, verify raw/doc created in DB

### Implementation

- [x] T025 [P1] [Risk: L] [P] [US1] Create Pydantic schemas for commands in src/schemas/command.py
  - **DoD**: CommandType enum 包含 SAVE, ANALYZE, PRACTICE, SEARCH, DELETE, PRIVACY; ParsedCommand schema 定義完整

- [x] T026 [P1] [Risk: M] [US1] Implement command parser in src/services/command_service.py
  - **DoD**: parse("入庫") 回傳 CommandType.SAVE；parse("查詢 考える") 回傳 CommandType.SEARCH + keyword

- [x] T027 [P1] [Risk: M] [US1] Implement save_raw handler in src/services/command_service.py
  - **DoD**: save_raw(user_id, text) 建立 raw_message + document (deferred)；回傳 doc_id

- [x] T028 [P1] [Risk: M] [US1] Create LINE webhook handler in src/api/webhook.py
  - **DoD**: POST /webhook 接收 LINE event；signature 驗證失敗回 400

- [x] T029 [P1] [Risk: M] [US1] Wire up "入庫" command to save raw and create deferred doc
  - **DoD**: LINE 發送「入庫」後，DB 有對應 raw_message + document (parse_status=deferred)

- [x] T030 [P1] [Risk: L] [US1] Add validation for empty/missing previous message
  - **DoD**: 無前一則訊息時回覆「請先貼上要入庫的內容」

- [x] T031 [P1] [Risk: L] [US1] Format LINE reply message for save confirmation
  - **DoD**: 回覆格式為「已入庫：#{doc_id[:8]}」

### Testing

- [x] T032 [P1] [Risk: L] [P] [US1] Create test fixtures with Japanese samples in tests/fixtures/
  - **DoD**: fixtures/japanese_samples.json 包含 10+ 真實日文素材（vocab, grammar, mixed）

- [x] T033 [P1] [Risk: L] [US1] Write unit tests for command parser in tests/unit/test_command_service.py
  - **DoD**: 測試涵蓋所有 CommandType；邊界案例（空白、大小寫）通過

- [x] T034 [P1] [Risk: M] [US1] Write integration test for save flow in tests/integration/test_save.py
  - **DoD**: 模擬 LINE webhook 完整流程；驗證 DB 寫入正確

**Checkpoint**: User Story 1 fully functional — "入庫" command works end-to-end

---

## Phase 4: User Story 2 - 素材分析 (P1)

**Goal**: 系統以 LLM 將素材結構化為 vocab/grammar items

**Spec Reference**: US2 in spec.md — FR-003, FR-011, FR-012

**Independent Test**: Have deferred doc, send "分析", verify items created with correct payload

### Implementation

- [x] T035 [P1] [Risk: L] [P] [US2] Create Pydantic schemas for Extractor in src/schemas/extractor.py
  - **DoD**: ExtractorRequest, ExtractorResponse, ExtractedItem schemas 符合 plan.md Extractor Output

- [x] T036 [P1] [Risk: H] [US2] Create Extractor prompt template in src/prompts/extractor.py
  - **DoD**: EXTRACTOR_SYSTEM_PROMPT 與 format_extractor_request() 符合 contracts/extractor-service.md

- [x] T037 [P1] [Risk: H] [US2] Implement ExtractorService in src/services/extractor_service.py
  - **DoD**: extract(doc_id) 回傳 ExtractorResponse；長文 (>2000 字) 限制 max_items=20

- [x] T038 [P1] [Risk: M] [US2] Wire up "分析" command to ExtractorService
  - **DoD**: LINE 發送「分析」後觸發 ExtractorService；無 deferred doc 時回覆提示

- [x] T039 [P1] [Risk: M] [US2] Implement item upsert logic (dedupe by user_id, item_type, key)
  - **DoD**: 重複 key 時更新 payload/confidence；不建立新 item

- [x] T040 [P1] [Risk: L] [US2] Update document parse_status after extraction
  - **DoD**: 成功後 parse_status=parsed；失敗後 parse_status=failed

- [x] T041 [P1] [Risk: L] [US2] Format LINE reply with extraction summary
  - **DoD**: 回覆格式為「抽到 N 個單字、M 個文法」

### Testing

- [x] T042 [P1] [Risk: L] [P] [US2] Create Extractor test fixtures in tests/fixtures/extractor/
  - **DoD**: 包含 vocab_only.json, grammar_only.json, mixed.json, empty.json 測試案例

- [x] T043 [P1] [Risk: H] [US2] Write unit tests for ExtractorService in tests/unit/test_extractor_service.py
  - **DoD**: Mock LLM 回應；驗證 item 建立邏輯；涵蓋 confidence 邊界

- [x] T044 [P1] [Risk: M] [US2] Write integration test for analyze flow in tests/integration/test_analyze.py
  - **DoD**: 完整流程測試；包含重複入庫場景驗證 upsert

**Checkpoint**: User Story 2 fully functional — "分析" extracts vocab/grammar correctly

---

## Phase 5: User Story 3 - 練習複習 (P1)

**Goal**: 使用者輸入「練習」即可得到與其資料庫相關的練習題

**Spec Reference**: US3 in spec.md — FR-004, FR-013, FR-014, FR-015

**Independent Test**: Have 5+ items, send "練習", receive 5 questions

### Implementation

- [x] T045 [P1] [Risk: L] [P] [US3] Create Pydantic schemas for Practice in src/schemas/practice.py
  - **DoD**: PracticeQuestion, PracticeSession schemas 定義完整；支援 vocab_recall/grammar_cloze

- [x] T046 [P1] [Risk: M] [US3] Implement item selection algorithm in src/services/practice_service.py
  - **DoD**: 優先順序：24h 新增 > 7 天內錯誤率高 > 最久未練 > 隨機；單元測試驗證順序

- [x] T047 [P1] [Risk: M] [US3] Implement vocab_recall question generator in src/services/practice_service.py
  - **DoD**: generate_vocab_recall(item) 回傳「『{meaning}』的日文是？」格式題目

- [x] T048 [P1] [Risk: M] [US3] Implement grammar_cloze question generator in src/services/practice_service.py
  - **DoD**: generate_grammar_cloze(item) 回傳挖空例句；挖空位置為文法 pattern

- [x] T049 [P1] [Risk: M] [US3] Wire up "練習" command to PracticeService
  - **DoD**: LINE 發送「練習」後回傳 5 題；session 資訊暫存（記憶體或 Redis）

- [x] T050 [P1] [Risk: L] [US3] Handle insufficient items case (< 5 items)
  - **DoD**: items < 5 時回覆「你的題庫還不夠，請先入庫更多素材（目前：N 個）」

- [x] T051 [P1] [Risk: L] [US3] Format LINE reply with practice questions
  - **DoD**: 多題以換行分隔；格式清晰易讀

### Testing

- [x] T052 [P1] [Risk: L] [P] [US3] Create Practice test fixtures in tests/fixtures/practice/
  - **DoD**: 包含 5+ vocab items, 5+ grammar items 的測試資料

- [x] T053 [P1] [Risk: M] [US3] Write unit tests for item selection in tests/unit/test_practice_service.py
  - **DoD**: 驗證優先順序邏輯；mock 時間測試 24h/7d 條件

- [x] T054 [P1] [Risk: M] [US3] Write integration test for practice flow in tests/integration/test_practice.py
  - **DoD**: 完整流程測試；驗證回傳題目數量與格式

**Checkpoint**: User Story 3 fully functional — "練習" generates appropriate questions

---

## MVP Validation Point

**MVP 包含**: US1 (入庫) + US2 (分析) + US3 (練習)

**驗收標準**:
- 使用者可在 3 分鐘內完成「入庫 - 分析 - 練習」完整循環
- LINE 實機測試通過
- 所有 P1 tests 通過

**決策點**: MVP 驗收後可部署，或繼續 US4-US7

---

## Phase 6: User Story 4 - 作答與判分 (P2)

**Goal**: 系統判分並給予回饋，記錄練習結果

**Spec Reference**: US4 in spec.md — FR-016, FR-017

**Independent Test**: Answer a question, verify is_correct and practice_log created

### Implementation

- [x] T055 [P2] [Risk: M] [US4] Implement answer grading logic in src/services/practice_service.py
  - **DoD**: grade_answer(expected, actual) 回傳 is_correct；支援 exact match + normalized match

- [x] T056 [P2] [Risk: M] [US4] Implement normalize comparison (kana/kanji, width conversion)
  - **DoD**: normalize_for_compare() 使用 src/lib/normalizer.py；「考える」==「かんがえる」為 True

- [x] T057 [P2] [Risk: M] [US4] Create practice session state tracking in src/services/session_service.py
  - **DoD**: SessionService 可 get/set 當前 session；支援 in-memory 或 Redis backend

- [x] T058 [P2] [Risk: M] [US4] Wire up answer messages to grader
  - **DoD**: 非指令訊息在 active session 時視為答案；呼叫 grader

- [x] T059 [P2] [Risk: L] [US4] Record practice_log for each answer
  - **DoD**: 每次作答建立 practice_log；包含 item_id, user_answer, is_correct

- [x] T060 [P2] [Risk: L] [US4] Format LINE reply with feedback (correct/incorrect, answer)
  - **DoD**: 正確回覆「正確！」；錯誤回覆「答案是：{correct_answer}」

### Testing

- [x] T061 [P2] [Risk: L] [P] [US4] Create grading test cases in tests/fixtures/grading/
  - **DoD**: 包含 exact_match, kana_kanji, width_conversion, wrong_answer 測試案例

- [x] T062 [P2] [Risk: M] [US4] Write unit tests for grader in tests/unit/test_grading.py
  - **DoD**: 涵蓋所有 normalize 規則；邊界案例（空白、標點）通過

- [x] T063 [P2] [Risk: M] [US4] Write integration test for answer flow in tests/integration/test_answer.py
  - **DoD**: 模擬練習 - 作答完整流程；驗證 practice_log 寫入

**Checkpoint**: User Story 4 fully functional — answers are graded and logged

---

## Phase 7: User Story 5 - 關鍵字查詢 (P2)

**Goal**: 使用者可搜尋並查看已入庫的 items

**Spec Reference**: US5 in spec.md — FR-005

**Independent Test**: Have items, send "查詢 考", receive matching items

### Implementation

- [x] T064 [P2] [Risk: M] [US5] Implement keyword search in ItemRepository
  - **DoD**: search_by_keyword(user_id, keyword) 搜尋 surface, reading, pattern 欄位；回傳 max 10 筆

- [x] T065 [P2] [Risk: L] [US5] Wire up "查詢 <keyword>" command to search
  - **DoD**: LINE 發送「查詢 考」後回傳匹配 items

- [x] T066 [P2] [Risk: L] [US5] Handle missing keyword case
  - **DoD**: 「查詢」無 keyword 時回覆「請提供查詢關鍵字，例如：查詢 考える」

- [x] T067 [P2] [Risk: L] [US5] Format LINE reply with search results (max 5)
  - **DoD**: 回覆格式為「找到 N 筆：\n1. {surface} - {meaning}\n...」；超過 5 筆顯示「...還有 M 筆」

### Testing

- [x] T068 [P2] [Risk: L] [US5] Write unit tests for search in tests/unit/test_search.py
  - **DoD**: 測試 partial match, no match, multiple matches 案例

- [x] T069 [P2] [Risk: M] [US5] Write integration test for search flow in tests/integration/test_search.py
  - **DoD**: 完整流程測試；驗證回傳格式正確

**Checkpoint**: User Story 5 fully functional — search returns relevant items

---

## Phase 8: User Story 6 - 刪除資料 (P3)

**Goal**: 使用者可刪除錯誤入庫的素材或清空所有資料

**Spec Reference**: US6 in spec.md — FR-006, FR-007, FR-018

**Independent Test**: Send "刪除最後一筆", verify soft delete; "清空資料" with confirmation

### Implementation

- [x] T070 [P3] [Risk: M] [US6] Implement soft delete for last raw/doc/items
  - **DoD**: delete_last(user_id) 將最近 raw/doc/items 的 is_deleted=true；回傳刪除數量

- [x] T071 [P3] [Risk: M] [US6] Implement "清空資料" with confirmation state
  - **DoD**: 第一次回覆確認提示；收到「確定清空資料」後執行軟刪除

- [x] T072 [P3] [Risk: L] [US6] Wire up delete commands to handlers
  - **DoD**: 「刪除最後一筆」與「清空資料」指令正確路由

- [x] T073 [P3] [Risk: L] [US6] Format LINE reply with delete confirmation
  - **DoD**: 刪除成功回覆「已刪除最後一筆」或「已清空 N 筆資料」

### Testing

- [x] T074 [P3] [Risk: L] [US6] Write unit tests for delete in tests/unit/test_delete.py
  - **DoD**: 測試軟刪除邏輯；驗證 is_deleted flag 正確設定

- [x] T075 [P3] [Risk: M] [US6] Write integration test for delete flow in tests/integration/test_delete.py
  - **DoD**: 測試二次確認流程；驗證清空後 items 不出現在查詢/練習

**Checkpoint**: User Story 6 fully functional — delete works with confirmation

---

## Phase 9: User Story 7 - 隱私資訊查詢 (P3)

**Goal**: 使用者可查詢資料保存與使用說明

**Spec Reference**: US7 in spec.md — FR-008

**Independent Test**: Send "隱私", receive privacy policy text

### Implementation

- [x] T076 [P3] [Risk: L] [US7] Create privacy policy text in src/templates/privacy.py
  - **DoD**: PRIVACY_TEXT 包含資料保存方式、LLM 使用說明、刪除方法

- [x] T077 [P3] [Risk: L] [US7] Wire up "隱私" command to return policy
  - **DoD**: LINE 發送「隱私」後回傳 PRIVACY_TEXT

- [x] T078 [P3] [Risk: L] [US7] Format LINE reply with privacy info
  - **DoD**: 回覆格式清晰；不超過 LINE 訊息長度限制

### Testing

- [x] T079 [P3] [Risk: L] [US7] Write integration test for privacy command in tests/integration/test_privacy.py
  - **DoD**: 驗證回覆內容包含必要資訊

**Checkpoint**: User Story 7 fully functional — privacy info displayed

---

## Phase 10: Router Service (LLM Fallback)

**Goal**: 非指令訊息由 LLM Router 判斷意圖

**Spec Reference**: FR-009, FR-010

**Independent Test**: Send ambiguous message, verify correct intent classification

### Implementation

- [x] T080 [P2] [Risk: L] [P] Create Pydantic schemas for Router in src/schemas/router.py
  - **DoD**: RouterRequest, RouterResponse schemas 符合 plan.md Router Output

- [x] T081 [P2] [Risk: H] Create Router prompt template in src/prompts/router.py
  - **DoD**: ROUTER_SYSTEM_PROMPT 與 format_router_request() 符合 contracts/router-service.md

- [x] T082 [P2] [Risk: H] Implement RouterService in src/services/router_service.py
  - **DoD**: classify(message) 回傳 RouterResponse；confidence < 0.5 觸發 fallback

- [x] T083 [P2] [Risk: M] Integrate Router into webhook handler for non-command messages
  - **DoD**: 硬規則指令失敗後呼叫 Router；依 intent 路由至對應 handler

- [x] T084 [P2] [Risk: M] Implement auto-save flow for high-confidence save intent
  - **DoD**: Router intent=save 且 confidence>=0.80 時自動入庫並引導分析

- [x] T085 [P2] [Risk: M] Implement chat fallback for learning questions
  - **DoD**: intent=chat 時呼叫 LLM 生成學習相關回覆

### Testing

- [x] T086 [P2] [Risk: L] [P] Create Router test fixtures in tests/fixtures/router/
  - **DoD**: 包含 save_intent, practice_intent, chat_intent, ambiguous 測試案例

- [x] T087 [P2] [Risk: H] Write unit tests for RouterService in tests/unit/test_router_service.py
  - **DoD**: Mock LLM 回應；驗證各 intent 分類；測試 fallback 觸發

- [x] T088 [P2] [Risk: M] Write integration test for router flow in tests/integration/test_router.py
  - **DoD**: 完整流程測試；驗證非指令訊息正確路由

**Checkpoint**: Router handles ambiguous inputs correctly

---

## Phase 11: Polish and Cross-Cutting

**Purpose**: Improvements that affect multiple user stories

### Documentation

- [x] T089 [P3] [Risk: L] [P] Update README.md with setup and usage instructions
  - **DoD**: README 包含安裝步驟、環境變數、啟動指令、LINE Bot 設定

- [ ] T090 [P3] [Risk: L] [P] Add API documentation comments to all services
  - **DoD**: 所有 public method 有 docstring；參數與回傳值有型別標註

- [x] T091 [P3] [Risk: L] [P] Create deployment guide in docs/deployment.md
  - **DoD**: 包含 Railway/Render 部署步驟、環境變數設定、troubleshooting

### Error Handling and Logging

- [ ] T092 [P2] [Risk: M] Implement structured logging with request_id
  - **DoD**: 所有 log 包含 request_id；JSON 格式輸出；可依 level 過濾

- [ ] T093 [P2] [Risk: M] Add LLM trace logging (model, tokens, latency) per FR-020
  - **DoD**: 每次 LLM 呼叫記錄 model, input_tokens, output_tokens, latency_ms 至 log 與 llm_trace 欄位

- [ ] T094 [P2] [Risk: H] Implement graceful LLM failure handling per NFR-004
  - **DoD**: LLM 失敗時回覆「我剛剛卡住了，你可以再試一次」；raw 保留不丟失

- [ ] T095 [P2] [Risk: M] Add rate limiting for LLM calls
  - **DoD**: 單一 user 每分鐘 LLM 呼叫上限 10 次；超過時回覆提示

### Performance and Security

- [x] T096 [P1] [Risk: M] Implement user_id hashing per NFR-003
  - **DoD**: hash_user_id(line_user_id) 使用 SHA-256 + salt；salt 從環境變數讀取

- [x] T097 [P1] [Risk: M] Add LINE signature verification
  - **DoD**: webhook 請求 signature 驗證失敗回 400；驗證邏輯符合 LINE 規範

- [ ] T098 [P2] [Risk: H] Performance test: verify P95 < 3s for practice per NFR-001
  - **DoD**: 使用 locust 或 k6 測試；100 requests P95 < 3s；測試報告產出

- [ ] T099 [P2] [Risk: M] Security review: verify no credential leakage
  - **DoD**: 檢查所有 log 不含 API keys/tokens；.env 不進 git；secrets 使用環境變數

### Capacity and NFR Testing

- [ ] T100 [P2] [Risk: M] Capacity test: verify 1000 items per user per NFR-002
  - **DoD**: 建立 1000 items 後查詢/練習仍 < 3s；無 memory leak

### Deployment

- [x] T101 [P2] [Risk: M] Create Dockerfile
  - **DoD**: `docker build` 成功；`docker run` 可啟動 API server

- [x] T102 [P2] [Risk: L] Create docker-compose.yml for local development
  - **DoD**: `docker-compose up` 啟動 app + postgres；可本地測試完整流程

- [ ] T103 [P2] [Risk: M] Setup Railway/Render deployment configuration
  - **DoD**: 部署成功；webhook URL 可接收 LINE 事件

- [ ] T104 [P2] [Risk: L] Configure production environment variables
  - **DoD**: 所有 secrets 設定於 Railway/Render；不 hardcode

**Checkpoint**: Production-ready deployment

---

## Dependencies Summary

### Phase Dependencies

```
Phase 1 (Setup)
    |
    v
Phase 2 (Foundation) <-- BLOCKS all user stories
    |
    v
Phase 3-9 (User Stories) <-- Can run sequentially (recommended for solo)
    |
    v
Phase 10 (Router) <-- Enhances existing commands
    |
    v
Phase 11 (Polish)
```

### User Story Independence

| Story | Can Start After | Dependencies |
|-------|-----------------|--------------|
| US1 (入庫) | Phase 2 | None |
| US2 (分析) | Phase 2 | LLM client ready |
| US3 (練習) | Phase 2 | Items exist (needs US2 or test data) |
| US4 (判分) | US3 | Practice questions exist |
| US5 (查詢) | Phase 2 | Items exist |
| US6 (刪除) | Phase 2 | Raw/docs exist |
| US7 (隱私) | Phase 2 | None |

### Parallel Opportunities per Phase

| Phase | Parallel Tasks |
|-------|---------------|
| Phase 1 | T003, T004, T005, T006 |
| Phase 2 | T009-T012 (models), T015-T022 (infrastructure) |
| Phase 3 | T025, T032 |
| Phase 4 | T035, T042 |
| Phase 5 | T045, T052 |
| Phase 6 | T061 |
| Phase 10 | T080, T086 |
| Phase 11 | T089, T090, T091 |

---

## Implementation Strategy

### MVP First (Recommended)

1. Complete Phase 1: Setup (~0.5 day)
2. Complete Phase 2: Foundation (~1.5 days)
3. Complete Phase 3: US1 入庫 (~1 day)
4. Complete Phase 4: US2 分析 (~1.5 days)
5. Complete Phase 5: US3 練習 (~1 day)
6. **STOP and VALIDATE**: Test US1-US3 end-to-end
7. Deploy MVP if ready
8. Continue to US4-US7, Router, Polish

### Incremental Delivery

```
Setup --> Foundation --> US1 (入庫) --> US2 (分析) --> US3 (練習) --> MVP!
                                                                       |
                                                        US4 (判分) <---+
                                                                       |
                                                        US5 (查詢) <---+
                                                                       |
                                                        US6 (刪除) <---+
                                                                       |
                                                        US7 (隱私) <---+
                                                                       |
                                                        Router <-------+
                                                                       |
                                                        Polish <-------+
```

---

## Estimated Timeline

| Phase | Tasks | Estimate | Cumulative |
|-------|-------|----------|------------|
| Phase 1: Setup | T001-T006 | 0.5 day | 0.5 day |
| Phase 2: Foundation | T007-T024 | 1.5 days | 2 days |
| Phase 3: US1 入庫 | T025-T034 | 1 day | 3 days |
| Phase 4: US2 分析 | T035-T044 | 1.5 days | 4.5 days |
| Phase 5: US3 練習 | T045-T054 | 1 day | 5.5 days |
| Phase 6: US4 判分 | T055-T063 | 1 day | 6.5 days |
| Phase 7: US5 查詢 | T064-T069 | 0.5 day | 7 days |
| Phase 8: US6 刪除 | T070-T075 | 0.5 day | 7.5 days |
| Phase 9: US7 隱私 | T076-T079 | 0.25 day | 7.75 days |
| Phase 10: Router | T080-T088 | 1 day | 8.75 days |
| Phase 11: Polish | T089-T104 | 1.5 days | 10.25 days |
| **Total** | **104 tasks** | **~10.5 days** | |

---

## Notes

- Commit after each task or logical group
- Stop at any checkpoint to validate independently
- If blocked, document blocker and move to parallel task
- Update this file as tasks complete: change `- [ ]` to `- [x]`

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-01-27 | Initial task decomposition based on plan v1.0.0 |
| 1.1.0 | 2026-01-27 | Added DoD, Risk Level, Priority per Constitution Section 6; Added T100 for NFR-002 capacity test; Added session_service.py (T057) |
