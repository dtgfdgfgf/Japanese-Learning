# Feature Specification: LINE 日語學習助教 Bot

**Feature ID**: `001-line-jp-learning`  
**Created**: 2026-01-27  
**Status**: Draft  
**Version**: 1.0.0

---

## Problem / Goal

日語進階學習者在日常接觸到的單字、文法、句子等素材，缺乏一個低摩擦、可隨手保存、並能轉化為練習題的工具。現有工具（如 Anki、筆記軟體）需要額外步驟或切換情境，導致素材「收集但不練習」。

**目標**：提供一個透過 LINE 即可完成「素材入庫 → 結構化分析 → 練習複習」完整循環的個人化日語學習助手。

---

## Actors

- **日語進階學習者**：主要使用者，透過 LINE 貼入日文素材、觸發分析與練習
- **LINE Bot（系統）**：接收訊息、執行指令、呼叫 LLM 進行意圖判斷與結構化抽取
- **LLM 服務**：內部元件，負責 Router（意圖判斷）、Extractor（結構化抽取）、Practice Generator（出題）

---

## User Scenarios & Testing

### User Story 1 - 素材入庫 (Priority: P1)

使用者在閱讀日文內容時發現想記住的單字或文法，複製貼上到 LINE 聊天視窗，輸入「入庫」指令，系統立即保存該素材。

**Why this priority**: 入庫是整個系統的資料來源，沒有入庫就沒有後續的分析與練習。這是最基礎且必要的功能。

**Independent Test**: 單獨部署 LINE Webhook + 資料庫，驗證使用者可成功保存素材。

**Acceptance Scenarios**:

1. **Given** 使用者已加入 LINE Bot 好友，**When** 使用者貼上一段日文「考える」並輸入「入庫」，**Then** 系統回覆「已入庫：#doc_id」並將素材存入資料庫
2. **Given** 使用者未貼上任何訊息，**When** 使用者直接輸入「入庫」，**Then** 系統回覆「請先貼上要入庫的內容」
3. **Given** 使用者貼上非日文內容（如純中文），**When** 使用者輸入「入庫」，**Then** 系統仍保存並標記 lang=unknown，但提醒「這段內容可能不是日文」

---

### User Story 2 - 素材分析 (Priority: P1)

使用者入庫素材後，輸入「分析」指令，系統以 LLM 將素材結構化為可練習的單字（vocab）或文法（grammar）項目。

**Why this priority**: 分析是將原始素材轉換為可練習 items 的關鍵步驟，與入庫同為核心功能。

**Independent Test**: 準備 10-20 筆真實日文素材，驗證 Extractor 能正確抽取 vocab/grammar。

**Acceptance Scenarios**:

1. **Given** 使用者已入庫一段包含「考える」的日文，**When** 使用者輸入「分析」，**Then** 系統回覆「抽到 1 個單字」並建立對應的 vocab item
2. **Given** 使用者已入庫包含「〜てしまう」的句子，**When** 使用者輸入「分析」，**Then** 系統回覆「抽到 1 個文法」並建立對應的 grammar item
3. **Given** 使用者沒有任何待分析的文件，**When** 使用者輸入「分析」，**Then** 系統回覆「目前沒有需要分析的內容」

---

### User Story 3 - 練習複習 (Priority: P1)

使用者累積一定數量的 items 後，輸入「練習」指令，系統從使用者的 items 中選題並出 5 題練習。

**Why this priority**: 練習是學習閉環的核心，讓使用者能主動複習已入庫的素材。

**Independent Test**: 預先建立 5+ 個 items，驗證系統能出題並記錄作答結果。

**Acceptance Scenarios**:

1. **Given** 使用者已有 5 個以上的 vocab items，**When** 使用者輸入「練習」，**Then** 系統回覆 5 題 vocab_recall 題目（如「『思考』的日文是？」）
2. **Given** 使用者已有 grammar items，**When** 使用者輸入「練習」，**Then** 系統回覆 grammar_cloze 題目（挖空填文法）
3. **Given** 使用者 items 數量少於 5 個，**When** 使用者輸入「練習」，**Then** 系統回覆「你的題庫還不夠，請先入庫更多素材（目前：N 個）」

---

### User Story 4 - 作答與判分 (Priority: P2)

使用者收到練習題後，回覆答案，系統判分並給予回饋，同時記錄練習結果。

**Why this priority**: 判分與紀錄是實現「錯題優先」的基礎，但可先以簡化版（exact match）上線。

**Independent Test**: 模擬使用者作答，驗證判分邏輯與 practice_logs 寫入。

**Acceptance Scenarios**:

1. **Given** 系統出題「『思考』的日文是？」且正確答案為「考える」，**When** 使用者回覆「考える」，**Then** 系統回覆「正確！」並記錄 is_correct=true
2. **Given** 系統出題且正確答案為「考える」，**When** 使用者回覆「かんがえる」（假名），**Then** 系統回覆「正確！」（允許假名/漢字互換）
3. **Given** 系統出題，**When** 使用者回覆錯誤答案，**Then** 系統回覆「答案是：考える」並記錄 is_correct=false

---

### User Story 5 - 關鍵字查詢 (Priority: P2)

使用者想找特定素材時，輸入「查詢 <keyword>」，系統搜尋並回傳匹配的 items。

**Why this priority**: 查詢功能增加資料可用性，但非核心學習循環。

**Independent Test**: 預先建立 items，驗證關鍵字搜尋結果正確。

**Acceptance Scenarios**:

1. **Given** 使用者有 vocab item surface=「考える」，**When** 使用者輸入「查詢 考」，**Then** 系統回覆包含該 item 的摘要
2. **Given** 使用者沒有匹配的 items，**When** 使用者輸入「查詢 xyz」，**Then** 系統回覆「找不到相關內容」
3. **Given** 使用者輸入「查詢」但沒有關鍵字，**When** 訊息送出，**Then** 系統回覆「請提供查詢關鍵字，例如：查詢 考える」

---

### User Story 6 - 刪除資料 (Priority: P3)

使用者想刪除錯誤入庫的素材或清空所有資料時，可使用刪除指令。

**Why this priority**: 資料管理功能，重要但非日常高頻使用。

**Independent Test**: 驗證軟刪除邏輯與二次確認流程。

**Acceptance Scenarios**:

1. **Given** 使用者有至少一筆 raw/doc，**When** 使用者輸入「刪除最後一筆」，**Then** 系統將最近一筆 raw/doc/items 標記 is_deleted=true 並回覆確認
2. **Given** 使用者輸入「清空資料」，**When** 訊息送出，**Then** 系統回覆「確定要清空所有資料嗎？請回覆『確定清空資料』」
3. **Given** 系統等待二次確認，**When** 使用者回覆「確定清空資料」，**Then** 系統將該 user 所有資料軟刪除並回覆「已清空」

---

### User Story 7 - 隱私資訊查詢 (Priority: P3)

使用者想了解資料如何保存與使用時，輸入「隱私」指令。

**Why this priority**: 合規與信任建立，但非核心功能。

**Independent Test**: 驗證回覆內容符合隱私政策。

**Acceptance Scenarios**:

1. **Given** 使用者輸入「隱私」，**When** 訊息送出，**Then** 系統回覆資料保存方式、LLM 使用說明、刪除方法

---

### Edge Cases

- **長文處理**：當使用者貼入超過 2000 字的長文時，系統採用 deferred parse，先存 raw，分析時分批或限制 max_items_per_doc=20
- **LLM 服務不可用**：當 LLM API 回應失敗或超時時，系統回覆「我剛剛卡住了，你可以再試一次：分析/練習」並保留 raw
- **重複入庫**：使用者入庫相同內容時，允許重複 raw，但 items 依 (user_id, item_type, key) upsert 避免重複
- **非日文內容**：使用者貼入純中文或英文時，仍保存，標記 lang=unknown，分析時可能產生空 items 或 warnings
- **練習中途離開**：使用者收到題目後未作答就離開，不強制 session，下次「練習」重新出題

---

## Functional Requirements

### 指令處理

- **FR-001**: 系統必須優先執行硬規則指令解析（入庫、分析、練習、查詢、刪除、隱私），再 fallback 到 LLM Router
- **FR-002**: 系統必須支援「入庫」指令，將使用者上一則訊息存入 raw_messages 與 documents 表
- **FR-003**: 系統必須支援「分析」指令，對最近一筆 deferred 文件執行 LLM Extractor 並產生 items
- **FR-004**: 系統必須支援「練習」指令，從使用者的 items 中選取 5 題並回傳
- **FR-005**: 系統必須支援「查詢 <keyword>」指令，搜尋 vocab.surface、vocab.reading、grammar.pattern 欄位
- **FR-006**: 系統必須支援「刪除最後一筆」指令，軟刪除最近一筆 raw/doc/items
- **FR-007**: 系統必須支援「清空資料」指令，需二次確認後軟刪除該 user 所有資料
- **FR-008**: 系統必須支援「隱私」指令，回覆資料保存與使用說明

### LLM 整合

- **FR-009**: Router 必須輸出結構化 JSON，包含 intent、confidence、entities
- **FR-010**: 當 Router 判斷 intent=save 且 confidence>=0.80 時，系統可自動入庫（deferred）並引導使用者分析
- **FR-011**: Extractor 必須輸出結構化 JSON，包含 lang、doc_type、items 陣列
- **FR-012**: 每個 item 必須包含 item_type（vocab/grammar）、key、payload、source_quote、confidence

### 練習系統

- **FR-013**: 系統必須支援 vocab_recall 題型（中文 → 日文）
- **FR-014**: 系統必須支援 grammar_cloze 題型（例句挖空）
- **FR-015**: Item 選取必須依優先順序：最近 24 小時新增 > 近 7 天錯誤率高 > 最久未練 > 隨機
- **FR-016**: 判分必須支援 normalize 比對（假名/漢字互換、全半形轉換）
- **FR-017**: 每次作答必須記錄至 practice_logs（item_id、practice_type、user_answer、is_correct）

### 資料管理

- **FR-018**: 所有刪除操作必須為軟刪除（is_deleted=true）
- **FR-019**: Items 必須依 (user_id, item_type, key) 做 upsert，避免重複
- **FR-020**: 系統必須記錄 LLM 呼叫的 trace 資訊（model、tokens、latency）

---

## Non-Functional Requirements

- **NFR-001**: 練習回覆 P95 回應時間必須 < 3 秒（不含 deferred parse 任務）
- **NFR-002**: 系統必須支援單一使用者累積至少 1000 個 items
- **NFR-003**: 所有使用者資料必須以 user_id hash 儲存，不直接儲存 LINE user ID
- **NFR-004**: LLM API 失敗時，系統必須 graceful degradation，保留 raw 並提示重試
- **NFR-005**: 資料庫必須支援軟刪除與資料恢復

---

## Key Entities

- **Raw Message**: 使用者原始輸入，不可變，包含 raw_text、channel、timestamp
- **Document**: 對應一次入庫的文件，包含 lang、doc_type、parse_status、tags
- **Item**: 可練習的學習單元，分為 vocab（單字）與 grammar（文法）兩種類型
- **Practice Log**: 練習紀錄，包含題型、使用者答案、正確與否、時間戳

---

## Success Criteria

- **SC-001**: 使用者可在 3 分鐘內完成「入庫 → 分析 → 練習」完整循環
- **SC-002**: D1 留存率：使用者隔天至少再次使用一次（入庫或練習）
- **SC-003**: 使用者 1 週內可累積至少 30 個 items
- **SC-004**: 使用者 1 週內可產生至少 10 次練習互動
- **SC-005**: Extractor 對標準日文素材的抽取成功率至少 80%

---

## Out of Scope

- 多人/群組學習功能
- 聽力、作文批改、影子跟讀等進階題型
- 與 Yomitan/Migaku/Anki 的自動同步
- 向量檢索（語意搜尋）
- 完整 SRS 演算法（SM-2/FSRS）
- 統計面板與資料匯出功能

---

## Assumptions

- 使用者為日語進階學習者，對指令式互動接受度高
- 使用者已有 LINE 帳號且熟悉 LINE Bot 基本操作
- LLM API（如 OpenAI）可穩定提供服務
- 單一使用者的資料量在 MVP 階段不會超過 1000 items

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-01-27 | Initial specification based on discovery output |
