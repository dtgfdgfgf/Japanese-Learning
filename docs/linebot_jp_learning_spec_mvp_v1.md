# LINE 日語學習助教 Bot — 可開工規格（MVP v1）
> 專案：日語學習（LINE 手動入庫 + LLM 路由 + 單字/文法練習）  
> 時區：Asia/Taipei  
> 版本：v1（可開工）

---

## 0. Decision Log（已定案）
- 主流程：A（LINE 手動入庫）
- Bot 角色：日文學習助教（非通用聊天）
- 成本策略：使用者輸入字數「產品層面不設上限」，但工程上採 **長文延後分析（deferred parse）**
- 隱私策略：不提供關閉 LLM；提供 **關鍵字查詢 / 刪除** 功能
- 練習範圍：單字、文法（MVP 先做 1–2 題型）
- 「用途判斷」：僅用於 **路由意圖**（save / practice / delete / search / chat / help）

---

## 1. 產品目標與成功指標
### 1.1 目標（MVP）
1. 使用者可在 LINE 將日文學習素材（單字/句子/段落）手動貼入並保存。
2. 系統可將素材結構化為可練習的 Item（vocab/grammar）。
3. 使用者輸入「練習」即可得到與其資料庫相關的單字/文法練習。
4. 系統記錄練習結果，支援基礎的錯題/久未練優先。

### 1.2 非目標（MVP 不做）
- 多題型的大而全練習（聽力、作文批改、影子跟讀等）
- 向量檢索（語意搜尋）
- 與 Yomitan/Migaku/Anki 的自動同步
- 多人共享資料庫 / 群組學習

### 1.3 成功指標（可驗收）
- D1 留存：使用者隔天至少再次使用一次（入庫或練習）
- 1 週內：累積 ≥ 30 個 items；可產生 ≥ 10 次練習互動
- 練習回覆：P95 回應時間 < 3 秒（不含延後分析任務）

---

## 2. 使用者體驗（UX）與訊息流程

## 2.1 指令集（硬規則）
> 指令解析在任何 LLM 之前執行（deterministic first）。

- `入庫`：將「上一則使用者訊息」存入 Raw，回傳 `#raw_id` 與 `#doc_id`
- `分析`：對「最近一份 deferred/未分析文件」執行 Canonical 抽取，並回覆摘要
- `練習`：出 5 題（MVP：vocab recall / grammar cloze 兩種之一，或依內容偏好自動選）
- `查詢 <keyword>`：以關鍵字在 items/documents 搜尋（surface/pattern/tags）
- `刪除最後一筆`：刪除最近一筆 raw/doc 與其 items（軟刪除）
- `清空資料`：刪除該 user 全部資料（軟刪除；需二次確認）
- `隱私`：回覆資料如何保存、如何使用 LLM、如何刪除

> 可選（第二階段）：`統計`（近 7 天入庫量、練習次數、正確率）

## 2.2 非指令訊息（LLM fallback）
- 若未命中硬規則指令：送入 **Router LLM**（意圖判斷 JSON）
- Router 結果可能導向：
  - `save`：提示使用者輸入「入庫」或自動入庫（見 2.3）
  - `practice`：直接走練習流程
  - `search`：走查詢流程
  - `delete`：走刪除流程（需二次確認的則引導）
  - `chat`：以「日文學習助教」回覆（限制在學習情境）
  - `help/other`：回覆可用指令與示例

## 2.3 自動入庫策略（MVP 建議）
雖然主流程是「手動入庫」，仍建議提供保守的自動入庫：
- 若 Router 判斷 `intent=save` 且 `confidence>=0.80`：
  - 先保存 raw/doc（`parse_status=deferred`），回覆：
    - 「已幫你存起來。要我現在分析成單字/文法 items 嗎？（回覆：分析）」
- 若 `confidence<0.80`：
  - 不自動入庫，回覆兩個選項：
    - 「你想 1) 入庫 2) 問我問題？」

---

## 3. 系統架構（高階）
- LINE Webhook → API Server（Router + Command Handler）
- Database（PostgreSQL / Supabase）
- LLM API（Router / Canonical Extractor / Practice Generator）
- Optional：Queue/Worker（分析長文時的延後任務；MVP 可先同步但設門檻）

---

## 4. 資料模型（DB Schema）

> 原則：Raw 不可變；Canonical 可重建（版本化）；Practice 可統計。  
> 建議：PostgreSQL，payload 使用 JSONB。

## 4.1 `raw_messages`
| 欄位 | 型別 | 說明 |
|---|---|---|
| raw_id | uuid (PK) | 原始訊息 ID |
| user_id | text (indexed) | LINE user id 的 hash |
| channel | text | 固定 `line` |
| raw_text | text | 原文 |
| raw_meta | jsonb | message_id, timestamp, user_note 等 |
| created_at | timestamptz | 建立時間 |
| is_deleted | boolean | 軟刪除 |

索引：`(user_id, created_at desc)`, `GIN(raw_meta)`（可選）

## 4.2 `documents`
| 欄位 | 型別 | 說明 |
|---|---|---|
| doc_id | uuid (PK) | 文件 ID |
| raw_id | uuid (FK) | 對應 raw |
| user_id | text (indexed) | 使用者 |
| lang | text | `ja/mixed/unknown` |
| doc_type | text | `vocab/grammar/mixed/text` |
| summary | text | 可選 |
| tags | jsonb | array of strings |
| parse_status | text | `parsed/deferred/failed` |
| parser_version | text | 例如 `canon_v1` |
| llm_trace | jsonb | model/prompt/tokens/cost 等（可選但推薦） |
| created_at | timestamptz | 建立時間 |
| updated_at | timestamptz | 更新時間 |

索引：`(user_id, created_at desc)`, `GIN(tags)`（可選）

## 4.3 `items`
> 用單表承載 `vocab/grammar`，以 `item_type + payload` 表示差異。

| 欄位 | 型別 | 說明 |
|---|---|---|
| item_id | uuid (PK) | item |
| user_id | text (indexed) | 使用者 |
| doc_id | uuid (FK) | 所屬文件 |
| item_type | text | `vocab/grammar` |
| key | text (indexed) | 去重/索引 key（normalize） |
| payload | jsonb | 依類型的欄位 |
| source_quote | text | 原文片段（展示/追溯） |
| confidence | float | 0~1 |
| created_at | timestamptz | |
| is_deleted | boolean | 軟刪除 |

索引建議：
- `unique (user_id, item_type, key) where is_deleted=false`（避免重複）
- `GIN(payload)`（可選，視查詢需要）

### 4.3.1 vocab payload（MVP 最小）
```json
{
  "surface": "考える",
  "reading": "かんがえる",
  "pos": "verb",
  "glossary_zh": ["思考", "考慮"],
  "example_ja": "もう少し考えてみます。",
  "example_zh": "我再想想看。",
  "level": "N3",
  "notes": "可用於委婉回覆"
}
```

`key` 規則：`vocab:<normalized_surface>`

### 4.3.2 grammar payload（MVP 最小）
```json
{
  "pattern": "〜てしまう",
  "meaning_zh": "表示遺憾/不小心做了…；也可表示事情完全完成",
  "usage": [
    "常見語感是『不小心』或『遺憾』",
    "口語常縮約為 〜ちゃう / 〜じゃう"
  ],
  "form_notes": "Vて + しまう",
  "example_ja": "財布を忘れてしまった。",
  "example_zh": "我不小心忘了帶錢包。",
  "level": "N3",
  "common_mistakes": []
}
```

`key` 規則：`grammar:<normalized_pattern>`

## 4.4 `practice_logs`
| 欄位 | 型別 | 說明 |
|---|---|---|
| log_id | uuid (PK) | |
| user_id | text (indexed) | |
| item_id | uuid (FK) | |
| practice_type | text | `vocab_recall` / `grammar_cloze`（MVP） |
| prompt_snapshot | text | 題目（可選） |
| user_answer | text | 使用者回答 |
| is_correct | boolean | |
| score | float | 可選 |
| feedback | text | 可選（錯誤說明） |
| created_at | timestamptz | |

索引：`(user_id, created_at desc)`, `(user_id, item_id, created_at desc)`

---

## 5. Router（意圖判斷）規格

## 5.1 Router 輸入
- `user_message`：使用者當前訊息
- `recent_messages`：最近 N 輪（建議 N=6；MVP 也可先不用）
- `user_context`：可選（例如：最近入庫 doc_id、最近練習 item_type）

## 5.2 Router 輸出（JSON Schema）
```json
{
  "intent": "save | practice | delete | search | chat | help | other",
  "confidence": 0.0,
  "entities": {
    "keyword": "string | null",
    "delete_scope": "last | all | none",
    "practice_focus": "vocab | grammar | mixed | null"
  },
  "should_store_raw": true,
  "response_hint": "短提示文字（可選）"
}
```

## 5.3 Router 決策規則（伺服器端）
1. 先做硬規則指令解析（2.1）。命中即終止 Router。
2. 未命中 → 呼叫 Router LLM。
3. 若 `intent=save` 且 `confidence>=0.80`：自動存 raw/doc（deferred），並引導「分析」。
4. 若 `intent=practice`：走練習流程。
5. 若 `intent=search`：若 `entities.keyword` 缺失 → 回覆請提供關鍵字。
6. 若 `intent=delete`：
   - `delete_scope=all` 必須二次確認（例如回覆「確定清空資料」）。
7. 若 `intent=chat`：走日文學習助教對話。
8. 其他：回 `help`（列出指令與例子）。

---

## 6. Canonical 抽取（Extractor）規格

## 6.1 觸發時機
- 指令 `分析`
- 或自動入庫後使用者回覆「分析」
- 或使用者要求出題，但 doc 尚未 parsed

## 6.2 Extractor 輸入
- `raw_text`
- `lang_hint=ja`
- `extract_targets=["vocab","grammar"]`
- `max_items_per_doc`（建議 20；可防爆）

## 6.3 Extractor 輸出（JSON）
```json
{
  "lang": "ja | mixed | unknown",
  "doc_type": "vocab | grammar | mixed | text",
  "tags": [],
  "items": [
    {
      "item_type": "vocab",
      "key": "vocab:考える",
      "source_quote": "考える",
      "confidence": 0.92,
      "payload": {
        "surface": "考える",
        "reading": "かんがえる",
        "pos": "verb",
        "glossary_zh": ["思考", "考慮"],
        "example_ja": "もう少し考えてみます。",
        "example_zh": "我再想想看。",
        "level": "N3",
        "notes": ""
      }
    },
    {
      "item_type": "grammar",
      "key": "grammar:〜てしまう",
      "source_quote": "〜てしまう",
      "confidence": 0.88,
      "payload": {
        "pattern": "〜てしまう",
        "meaning_zh": "表示遺憾/不小心做了…；也可表示事情完全完成",
        "usage": ["..."],
        "form_notes": "Vて + しまう",
        "example_ja": "財布を忘れてしまった。",
        "example_zh": "我不小心忘了帶錢包。",
        "level": "N3",
        "common_mistakes": []
      }
    }
  ],
  "warnings": ["可選：內容太短/非日文/需要人工確認"]
}
```

## 6.4 伺服器端寫入規則
- 建立或更新 documents：
  - `lang/doc_type/tags/parse_status=parsed/parser_version`
- items：
  - 依 `(user_id, item_type, key)` upsert（若已存在且非 deleted，更新 payload/source_quote/confidence）
- 若抽取失敗：`parse_status=failed`，並回覆使用者可重試

---

## 7. 練習（Practice）規格

## 7.1 練習題型（MVP）
- `vocab_recall`：給中文 → 回日文（或反向；MVP 先固定一種）
- `grammar_cloze`：提供例句挖空 → 填入文法（pattern）或適當形式

## 7.2 Item 選取策略（無向量版）
優先順序（高到低）：
1. 最近 24 小時新增 items
2. 近 7 天錯誤率高的 items
3. 最久未練的 items
4. 隨機

> 需要的資料：practice_logs（錯誤率與 last_seen）

## 7.3 出題生成策略
- vocab：可不依賴 LLM（用 payload 直接生成題目），必要時用 LLM 產生多樣例句（第二階段）
- grammar_cloze：建議用 LLM 生成 cloze（但需嚴格 JSON 回傳，避免跑版）

### 7.3.1 練習生成輸出（JSON）
```json
{
  "practice_type": "vocab_recall",
  "items": [
    {
      "item_id": "uuid",
      "question": "『思考』的日文是？",
      "expected": ["考える"],
      "hint": "かんがえる",
      "explain": "可用於『我再想想看』"
    }
  ]
}
```

## 7.4 判分（MVP）
- vocab：`normalize(user_answer)` 與 `expected[]` 比對；可接受同義答案（第二階段）
- grammar：先做 exact/normalize；若失敗可用 LLM judge（需成本控制）

## 7.5 寫入 practice_logs
每題都記錄：`item_id, practice_type, user_answer, is_correct, feedback(optional)`

---

## 8. 查詢與刪除（關鍵字/管理）

## 8.1 查詢 `查詢 <keyword>`
- 搜尋範圍（MVP）：
  - vocab.surface, vocab.reading, glossary_zh（可先不做 glossary 搜尋也可）
  - grammar.pattern, meaning_zh
- 回覆格式：
  - 最多回 5 筆，附上簡短摘要與 `#item_id`（可選）

## 8.2 刪除
- `刪除最後一筆`：
  - 找最近一筆未刪除 raw → 對應 doc/items 一併 `is_deleted=true`
- `清空資料`：
  - 必須二次確認（使用者回覆「確定清空資料」）
  - 全表以 `user_id` 批次軟刪除

---

## 9. 隱私宣告（`隱私` 指令回覆內容範本）
MVP 建議回覆要點：
- 你貼給 bot 的內容會被保存於資料庫，以便提供練習與查詢。
- 內容可能會送到語言模型 API 進行「意圖判斷/結構化/出題」。
- 你可以使用 `刪除最後一筆` 或 `清空資料` 移除內容。
- 若需要，可提供匯出（第二階段）。

---

## 10. API 介面契約（伺服器內部）

## 10.1 Webhook Handler
- Input：LINE webhook event
- Output：0..n 個 LINE reply messages（依流程）

## 10.2 Command Service
- `handle_command(user_id, text, context) -> Reply[]`

## 10.3 Router Service
- `route(user_id, text, context) -> RouterResult`

## 10.4 Canonical Service
- `extract(doc_id) -> ExtractorResult`

## 10.5 Practice Service
- `generate_practice(user_id, focus=None) -> PracticeSet`
- `grade_answer(practice_session_id, answers[]) -> Result`（MVP 可不做 session，用逐題回覆）

---

## 11. 測試與驗收（Given/When/Then）

### 11.1 入庫
- Given 使用者貼上一段日文單字  
- When 使用者輸入 `入庫`  
- Then 系統建立 raw/doc（deferred 或 parsed），回覆 `已入庫：#doc_id`

### 11.2 分析
- Given 最近一筆 doc 為 deferred  
- When 使用者輸入 `分析`  
- Then 系統產生 vocab/grammar items，回覆抽取摘要（例如「抽到 3 個單字、1 個文法」）

### 11.3 練習
- Given 使用者已有 items ≥ 5  
- When 使用者輸入 `練習`  
- Then 回覆 5 題並能記錄對錯到 practice_logs

### 11.4 查詢
- Given 使用者有 vocab.surface=考える  
- When `查詢 考`  
- Then 回覆至少包含該 item 的摘要

### 11.5 刪除最後一筆
- Given 最近一筆 raw/doc 未刪除  
- When `刪除最後一筆`  
- Then raw/doc/items 皆標記 is_deleted=true，且後續練習不再出現

---

## 12. 部署與觀測（MVP）
- 日誌：每次 Router/Extractor/Practice 呼叫記錄 request_id、tokens、latency
- 指標：每日訊息數、入庫數、分析成功率、練習次數、平均回覆時間
- 錯誤處理：LLM 失敗時回覆「我剛剛卡住了，你可以再試一次：分析/練習」並保留 raw

---

## 13. LLM Prompts（要求結構輸出）

### 13.1 Router Prompt（摘要）
- 角色：日文學習助教的路由器
- 輸出：嚴格 JSON（5.2）
- 限制：若非學習情境，意圖傾向 `help/other`，引導指令

### 13.2 Extractor Prompt（摘要）
- 角色：日文學習內容結構化器
- 目標：抽出可練習的 vocab/grammar items
- 輸出：嚴格 JSON（6.3）
- 限制：避免幻想；不知道就留空或 warnings

### 13.3 Practice Generator Prompt（摘要）
- 角色：出題器（基於 items）
- 輸出：嚴格 JSON（7.3.1）
- 限制：題目短、可判分、避免多解

---

## 14. 後續擴充（Deferred Backlog）
- 匯出資料（CSV/JSON）
- 統計面板（正確率、錯題榜、N3/N2 分佈）
- 自動同步（Yomitan/AnkiConnect）
- 向量檢索（pgvector）與語意召回
- 更完整的 SRS（SM-2/FSRS）

