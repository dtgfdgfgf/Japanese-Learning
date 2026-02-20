# 開發者導覽：功能／指令修改地圖（LINE Bot）

> 目標讀者：初階工程師  
> 目標：快速知道「要改哪個功能，就去改哪支檔案、哪個函式」

---

## 1) 先用 2 分鐘理解整體流程

### 1.1 請求進入點

1. FastAPI 掛上 webhook router  
   - `src/main.py:154` `app.include_router(webhook_router)`
2. LINE 打到 `/webhook`  
   - `src/api/webhook.py:270` `@router.post("/webhook")`
3. 驗證簽名、解析事件  
   - `src/api/webhook.py:281-289`
4. 文字訊息走 `handle_message_event()`  
   - `src/api/webhook.py:340`

### 1.2 文字訊息處理順序（最重要）

`src/api/webhook.py:340-599`

1. 先清理輸入文字（NFKC、去隱形字元、去首尾引號）  
   - `_sanitize_text()` `src/api/webhook.py:100`
2. 用 regex 解析硬指令  
   - `parse_command()` `src/services/command_service.py:64`
3. 讀使用者狀態（mode、target_lang、pending_save、pending_delete、是否在練習中）  
   - `src/api/webhook.py:380-416`
4. 狀態守衛優先：`pending_delete` → `pending_save` → 練習答題 → 一般分派  
   - `src/api/webhook.py:448-535`
5. 指令分派  
   - `_dispatch_command()` `src/api/webhook.py:682`
6. 補 footer + quick reply 後回覆  
   - `src/api/webhook.py:559-584`

---

## 2) 指令對照表（改功能先看這裡）

| 使用者輸入 | 解析位置 | CommandType | 實際 handler | 核心邏輯 |
|---|---|---|---|---|
| `入庫` | `src/services/command_service.py:28` | `SAVE` | `_handle_save` (`src/api/webhook.py:734`) | `CommandService.save_raw()` 建立 `raw_messages + documents` |
| `1` | `src/services/command_service.py:26` | `CONFIRM_SAVE` | `_handle_confirm_save` (`src/api/webhook.py:770`) | 確認 pending_save 並入庫 |
| `<單字> save` | `src/services/command_service.py:27` | `WORD_SAVE` | `_handle_word_save` (`src/api/webhook.py:756`) | 直接入庫，不走查詢確認 |
| `分析` | `src/services/command_service.py:29` | `ANALYZE` | `_handle_analyze` (`src/api/webhook.py:820`) | `ExtractorService.extract()` |
| `練習` | `src/services/command_service.py:30` | `PRACTICE` | `_handle_practice` (`src/api/webhook.py:853`) | `PracticeService.create_session()` |
| `結束練習 / 停止練習` | `src/services/command_service.py:44` | `EXIT_PRACTICE` | `_handle_exit_practice` (`src/api/webhook.py:921`) | `SessionService.clear_session()` |
| `查詢 <關鍵字>` | `src/services/command_service.py:31` | `SEARCH` | `_handle_search` (`src/api/webhook.py:791`) | `ItemRepository.search_by_keyword()` |
| `刪除 <關鍵字>` | `src/services/command_service.py:33` | `DELETE_ITEM` | `_handle_delete_item` (`src/api/webhook.py:936`) | 單筆直刪 / 多筆待選 |
| `清空資料` | `src/services/command_service.py:35` | `DELETE_ALL` | `_handle_delete_all_request` (`src/api/webhook.py:1038`) | 設 delete confirm 狀態 |
| `確定清空資料` | `src/services/command_service.py:36` | `DELETE_CONFIRM` | `_handle_delete_confirm` (`src/api/webhook.py:1049`) | 清空（soft delete） |
| `說明 / 幫助 / help` | `src/services/command_service.py:38` | `HELP` | `_dispatch_command` help 分支 (`src/api/webhook.py:692`) | 回覆 `Messages.HELP` |
| `隱私` | `src/services/command_service.py:37` | `PRIVACY` | `_dispatch_command` privacy 分支 (`src/api/webhook.py:698`) | 回覆 `Messages.PRIVACY` |
| `用量 / cost` | `src/services/command_service.py:39` | `COST` | `_handle_cost` (`src/api/webhook.py:873`) | `CostService.get_usage_summary()` |
| `統計 / 進度` | `src/services/command_service.py:40` | `STATS` | `_handle_stats` (`src/api/webhook.py:888`) | `StatsService.get_stats_summary()` |
| `免費模式 / 便宜模式 / 嚴謹模式`、`切換免費/便宜/嚴謹` | `src/services/command_service.py:41-42` | `MODE_SWITCH` | pre-dispatch 儲存 profile (`src/api/webhook.py:417-428`) | `UserProfileRepository.set_mode()` |
| `英文 / 日文` | `src/services/command_service.py:43` | `SET_LANG` | pre-dispatch 儲存 profile (`src/api/webhook.py:431-443`) | `UserProfileRepository.set_target_lang()` |
| 其他輸入 | `parse_command -> UNKNOWN` | `UNKNOWN` | `_handle_unknown` (`src/api/webhook.py:1073`) | Router + heuristic + fallback |

---

## 3) 修改功能時，該去哪些檔案

## A. 入庫（save）流程

### 主要程式
- 指令解析：`src/services/command_service.py:24-45`
- 入庫 handler：`src/api/webhook.py:734-789`
- 寫入 DB：`src/services/command_service.py:119-165`
  - `RawMessageRepository.create_raw_message()` `src/repositories/raw_message_repo.py:26`
  - `DocumentRepository.create_document()` `src/repositories/document_repo.py:26`

### 你最常要改的地方
- 入庫成功文案：`src/templates/messages.py:67-69`
- 入庫預覽長度（預設 30）：`truncate_content_preview()` `src/templates/messages.py:419-424`
- pending 入庫 timeout（5 分鐘）：`src/repositories/user_state_repo.py:18`

### 可驗證測試
- `tests/unit/test_command_service.py`
- `tests/integration/test_save.py`

---

## B. 分析（analyze）流程

### 主要程式
- 入口：`_handle_analyze()` `src/api/webhook.py:820-850`
- 核心：`ExtractorService.extract()` `src/services/extractor_service.py:55`
- Prompt：`src/prompts/extractor.py`
- 抽取摘要訊息：`ExtractionSummary.to_message()` `src/schemas/extractor.py:158`

### 你最常要改的地方
- 抽取規則 / 輸出 JSON 結構：`src/prompts/extractor.py:9-190`
- 長文判定（2000）與 max_items：`src/services/extractor_service.py:28-30`
- 分析結果文案：`src/templates/messages.py:83-87`

### 可驗證測試
- `tests/unit/test_extractor_service.py`
- `tests/integration/test_analyze.py`

---

## C. 練習（practice）流程

### 主要程式
- 開始練習：`_handle_practice()` `src/api/webhook.py:853-870`
- 交答案：`_handle_practice_answer()` `src/api/webhook.py:903-918`
- 題目與評分：`PracticeService` `src/services/practice_service.py`
  - `create_session()` `:65`
  - `submit_answer()` `:408`
- Session 持久化（TTL 30 分鐘）：`src/repositories/practice_session_repo.py:15-93`

### 你最常要改的地方
- 最低題庫數（預設 5）：`MIN_ITEMS_FOR_PRACTICE` `src/services/practice_service.py:43`
- 題數（預設 5）：`create_session(... question_count=5)` `src/api/webhook.py:865`
- 題目文案格式：`PracticeQuestion.format_for_display()` `src/schemas/practice.py:55-72`
- 正確/錯誤/結算文案：`src/templates/messages.py:95-114`

### 可驗證測試
- `tests/unit/test_practice_service.py`
- `tests/integration/test_practice.py`

---

## D. 查詢（search）流程

### 主要程式
- handler：`_handle_search()` `src/api/webhook.py:791-818`
- DB 搜尋：`ItemRepository.search_by_keyword()` `src/repositories/item_repo.py:218`
- 顯示格式：`_format_search_results()` `src/api/webhook.py:1294-1324`

### 你最常要改的地方
- 查詢提示/無結果文案：`src/templates/messages.py:89-93`
- 查詢結果格式（含 reading/pronunciation 顯示）：`src/api/webhook.py:1301-1319`

### 可驗證測試
- `tests/unit/test_search.py`
- `tests/integration/test_search.py`

---

## E. 刪除（delete）流程

### 主要程式
- `刪除 <關鍵字>`：`_handle_delete_item()` `src/api/webhook.py:936`
- 多筆選號：`_handle_delete_select()` `src/api/webhook.py:995`
- 清空請求：`_handle_delete_all_request()` `src/api/webhook.py:1038`
- 清空確認：`_handle_delete_confirm()` `src/api/webhook.py:1049`
- 實際 soft delete：`DeleteService` `src/services/delete_service.py:25`

### timeout / 狀態控制
- 清空確認 timeout（60 秒）：`CONFIRMATION_TIMEOUT` `src/repositories/user_state_repo.py:15`
- pending delete timeout（5 分鐘）：`PENDING_DELETE_TIMEOUT` `src/repositories/user_state_repo.py:21`
- pending save timeout（5 分鐘）：`PENDING_SAVE_TIMEOUT` `src/repositories/user_state_repo.py:18`

### 可驗證測試
- `tests/unit/test_delete_item.py`
- `tests/unit/test_delete.py`
- `tests/integration/test_delete.py`

---

## F. 模式切換 / 語言切換

### 主要程式
- 指令解析與 mapping  
  - `MODE_NAME_MAP` `src/services/command_service.py:54`
  - `LANG_NAME_MAP` `src/services/command_service.py:48`
- 寫入使用者偏好：`src/api/webhook.py:417-443`
- Postback quick reply：`handle_postback_event()` `src/api/webhook.py:601-659`
- quick reply 按鈕內容：`build_mode_quick_replies()` `src/lib/line_client.py:326-349`
- 模式對應模型：`MODE_MODEL_MAP` `src/lib/llm_client.py:92-96`

### 可驗證測試
- `tests/unit/test_mode_switch.py`
- `tests/unit/test_webhook_postback.py`
- `tests/unit/test_llm_mode.py`

---

## G. UNKNOWN 輸入（Router + 啟發式）流程

### 主要程式
- `_handle_unknown()` `src/api/webhook.py:1073-1252`
- Router 分類：`RouterService.classify()` `src/services/router_service.py:35`
- LLM word 解釋：`get_word_explanation()` `src/services/router_service.py:261`
- Router prompt：`src/prompts/router.py:10-100`

### 關鍵行為
- 先過濾無意義內容、URL、羅馬字、不支援語言（`src/api/webhook.py:1085-1101`）
- 長文（>2000）直接入庫（`src/api/webhook.py:1106-1109`）
- 短單字會先查 DB，無資料才呼叫 LLM 並設 pending_save（`src/api/webhook.py:1131-1158`）

### 可驗證測試
- `tests/unit/test_router_service.py`
- `tests/unit/test_webhook_word_lookup.py`
- `tests/unit/test_webhook_edge_cases.py`

---

## 4) 要改「LINE 回覆文字」時，最準確的修改點

## 4.1 第一優先：`src/templates/messages.py`

大部分回覆都在 `_MESSAGES_ZH_TW`（`src/templates/messages.py:52`）：
- HELP：`"HELP"` `:165`
- PRIVACY：`"PRIVACY"` `:188`
- 入庫、分析、練習、查詢、刪除、用量、統計、footer 都在這裡

## 4.2 第二優先：少數硬編碼字串（容易漏）

以下不是走 `Messages`，要改文案時要一起看：
- `src/api/webhook.py:1154` `"API呼叫失敗，請聯絡開發者"`
- `src/api/webhook.py:1176` `"API呼叫失敗，請聯絡開發者"`
- `src/api/webhook.py:1182` 多單字提示字串（f-string）
- `src/api/webhook.py:1223` `"API呼叫失敗，請聯絡開發者"`
- `src/api/webhook.py:1267` 入庫後提示「輸入分析」
- `src/api/webhook.py:1294-1324` 查詢結果格式組裝（非模板）
- `src/services/delete_service.py:69-74` 刪除項目 label 格式

---

## 5) 常見改需求 → 修改位置速查

| 想改什麼 | 先改哪裡 | 可能連動 |
|---|---|---|
| 新增一個文字指令 | `src/services/command_service.py:24-45`（加 regex + CommandType） | `src/schemas/command.py`、`src/api/webhook.py:_dispatch_command` |
| 改「說明」內容 | `src/templates/messages.py` 的 `"HELP"` | 測試 `tests/unit/test_webhook_edge_cases.py` |
| 改「隱私」內容 | `src/templates/messages.py` 的 `"PRIVACY"` | `tests/integration/test_privacy.py` |
| 改入庫成功提示 | `src/templates/messages.py` `"SAVE_SUCCESS"` | `truncate_content_preview()` |
| 改長文直接入庫門檻 | `src/api/webhook.py:89` `LONG_TEXT_THRESHOLD` | `tests/unit/test_webhook_edge_cases.py` |
| 改練習題數 | `src/api/webhook.py:865` `question_count=5` | `PracticeService.create_session()` |
| 改練習最低題庫數 | `src/services/practice_service.py:43` | `tests/unit/test_practice_service.py` |
| 改模式對應模型 | `src/lib/llm_client.py:92-96` | `tests/unit/test_llm_mode.py` |
| 改 Router 判斷規則 | `src/services/router_service.py:_heuristic_classify` | `tests/unit/test_router_service.py` |
| 改刪除確認時效 | `src/repositories/user_state_repo.py:15` | `tests/unit/test_delete.py` |
| 改 pending 入庫時效 | `src/repositories/user_state_repo.py:18` | `tests/unit/test_webhook_edge_cases.py` |

---

## 6) 快速驗證指令（文件可驗證）

> 以下都是專案現有測試檔，可直接執行

```bash
pytest tests/unit/test_command_service.py -q
pytest tests/unit/test_webhook_edge_cases.py -q
pytest tests/unit/test_mode_switch.py tests/unit/test_webhook_postback.py -q
pytest tests/unit/test_router_service.py tests/unit/test_webhook_word_lookup.py -q
pytest tests/unit/test_practice_service.py tests/integration/test_practice.py -q
pytest tests/unit/test_delete_item.py tests/integration/test_delete.py -q
pytest tests/unit/test_usage_footer.py tests/unit/test_cost_display.py -q
```

---

## 7) 最短上手路徑（新手建議）

1. 先讀 `src/api/webhook.py`：`handle_message_event()` + `_dispatch_command()`
2. 再讀 `src/services/command_service.py`：`COMMAND_PATTERNS` + `parse_command()`
3. 想改文案就先查 `src/templates/messages.py`
4. 想改 AI 判斷就看 `RouterService` + `src/prompts/router.py`
5. 想改分析抽取就看 `ExtractorService` + `src/prompts/extractor.py`

如果你只記得一句話：  
**「指令解析在 `command_service.py`，執行分派在 `webhook.py`，文案在 `messages.py`。」**
