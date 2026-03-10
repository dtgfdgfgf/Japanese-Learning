# LINE 日語學習助教 Bot

透過 LINE Messaging API 提供「查詞 -> 入庫 -> 自動抽取 -> 練習 -> 追蹤」的個人化語言學習流程。  
目前支援日文與英文學習內容，後端以 FastAPI + PostgreSQL 實作，並依模式切換 Gemini / Claude。

> Project Type: internal historical sample and regression fixture  
> 本 README 以目前程式行為、設定檔與測試覆蓋到的功能為準。

## 目前功能

- 直接輸入單字或短詞，取得 LLM 解釋，5 分鐘內輸入 `1` 即可入庫
- 貼上長文後自動翻譯並進入 article mode，可在同一篇文章語境下查詞或查文法
- 輸入 `入庫` 會保存上一則素材，並在背景自動抽取單字與文法，完成後透過 LINE Push 通知
- 輸入 `練習` 會從已入庫項目產生 5 題複習，涵蓋單字 recall / meaning 與文法 cloze / usage
- 支援 `查詢`、`清單`、`刪除`、`清空資料`、`統計`、`用量`、模式切換與學習語言切換
- 每次回覆附帶 token / cost footer，並附上模式切換 Quick Reply
- 使用 hashed user ID、soft delete、ownership check 與 API trace log 管理資料

## 典型使用流程

1. 查詞：直接輸入 `考える` 或 `fit`，看完解釋後輸入 `1` 入庫
2. 入庫素材：貼上一段句子、筆記或整理好的清單，再輸入 `入庫`
3. 等待抽取：系統會背景分析素材，完成後推送「已抽取幾個單字 / 文法」
4. 練習複習：輸入 `練習` 開始答題，輸入 `結束練習` 可中途離開
5. 看進度：輸入 `統計` 或 `用量` 查看學習與 API 使用狀況
6. 讀文章：直接貼長文，系統會回全文翻譯並進入 article mode，查完輸入 `完成`

## 指令與互動

### 文字指令

| 指令 | 用途 |
|------|------|
| `入庫` | 保存上一則素材，並觸發背景抽取 |
| `1` | 確認把目前 pending save 的單字或多個單字入庫 |
| `<單字> save` | 直接將指定單字入庫，不走查詞確認 |
| `練習` | 開始 5 題練習 |
| `結束練習` / `停止練習` | 中止目前練習 session |
| `查詢 <keyword>` | 搜尋已入庫的單字或文法 |
| `清單` | 列出所有已入庫項目 |
| `單字清單` / `文法清單` | 依類型篩選清單 |
| `刪除 <keyword>` | 搜尋後刪除指定項目 |
| `清空資料` / `確定清空資料` | 二段式清空個人資料 |
| `統計` / `進度` | 查看學習進度與近 7 日練習結果 |
| `用量` / `cost` | 查看 API token 與費用統計 |
| `免費模式` / `便宜模式` / `嚴謹模式` | 切換 LLM 模式 |
| `切換免費` / `切換便宜` / `切換嚴謹` | 另一種模式切換寫法 |
| `英文` / `日文` | 切換目前學習語言 |
| `完成` | 結束 article mode |
| `說明` / `幫助` / `help` | 查看使用說明 |
| `隱私` | 查看隱私與資料保存說明 |

### 非指令互動

- 直接輸入單字或短詞：先查 DB，未命中時呼叫 LLM 做單字解釋
- 直接輸入多個英文單字：支援批次解釋與批次 pending save
- 直接貼 TSV / 試算表內容：會直接入庫並自動抽取
- 直接貼長文：回全文翻譯並進入 article mode
- 中文問句：走 LLM chat fallback，回覆學習相關問答

> `分析` 指令已移除。現在的流程是「入庫後自動抽取」。

## LLM 模式

| 模式 | Provider | Model | 說明 |
|------|----------|-------|------|
| `free` | Google | `gemini-3.1-flash-lite-preview` | 預設模式，成本最低 |
| `cheap` | Anthropic | `claude-sonnet-4-6` | 平衡速度與品質 |
| `rigorous` | Anthropic | `claude-opus-4-6` | 最重視回答品質 |

說明：
- `free` 模式需要設定 `GEMINI_API_KEY`
- 系統會在回覆 footer 顯示本次 token / cost 與今日使用量
- 模式切換除了文字指令，也可用 LINE Quick Reply postback

## 系統架構

| 層級 | 路徑 | 角色 |
|------|------|------|
| API / Presentation | `src/api/` | LINE webhook、middleware、事件分派 |
| Application | `src/services/` | 指令、查詞、抽取、練習、統計、刪除等流程 |
| Domain | `src/models/`, `src/schemas/` | ORM model、Pydantic schema、session 狀態 |
| Infrastructure | `src/repositories/`, `src/lib/` | DB repository、LINE client、LLM client、normalizer |
| Prompt / Template | `src/prompts/`, `src/templates/` | LLM prompt 與對使用者回覆文案 |

資料流：

1. LINE webhook 進入 `POST /webhook`
2. 先走硬規則指令解析，再根據輸入特徵決定查詞、文章模式或 chat fallback
3. `入庫` 會建立 `raw_messages` 與 `documents`
4. 背景抽取完成後，將 vocab / grammar 寫入 `items`
5. 練習過程寫入 `practice_sessions` 與 `practice_logs`
6. LLM 呼叫成本與 token 使用量寫入 `api_usage_logs`

## 技術棧

| 類別 | 技術 |
|------|------|
| Web Framework | FastAPI |
| Messaging | LINE Messaging API / `line-bot-sdk` v3 |
| Database | PostgreSQL + SQLAlchemy 2.0 async + `asyncpg` |
| Migration | Alembic |
| LLM | Anthropic Claude + Google Gemini |
| Validation / Config | Pydantic v2 + pydantic-settings |
| Testing | pytest + pytest-asyncio + pytest-cov |
| Tooling | ruff, black, mypy, pre-commit |

## 本地開發

### 前置需求

- Python 3.11+
- PostgreSQL 15+，或直接使用 `docker compose`
- LINE Messaging API channel
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`（如果要使用 `free` 模式）

### 啟動方式

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
alembic upgrade head
uvicorn src.main:app --reload --port 8000
```

服務啟動後可使用：

- `GET /health`：健康檢查
- `GET /`：簡單 welcome endpoint
- `POST /webhook`：LINE webhook 入口
- `GET /docs`、`GET /redoc`：僅在 `APP_ENV=development` 時開啟

### 使用 Docker Compose

```bash
docker compose up --build
```

補充：

- `docker-compose.yml` 會啟動 `app` + `postgres`，另有可選的 `adminer`
- `Dockerfile` 在啟動時會先執行 `alembic upgrade head`
- 若要開啟 Adminer，可使用 `docker compose --profile tools up`

## 主要環境變數

| 變數 | 必填 | 說明 |
|------|------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | yes | LINE Channel Access Token |
| `LINE_CHANNEL_SECRET` | yes | LINE Channel Secret |
| `DATABASE_URL` | yes | `postgresql+asyncpg://...` 連線字串 |
| `ANTHROPIC_API_KEY` | yes | Claude API Key |
| `GEMINI_API_KEY` | no | Gemini API Key；留空表示停用 `free` mode |
| `USER_ID_SALT` | yes | 用於 hash LINE user ID，最少 32 字元 |
| `APP_ENV` | no | `development` / `staging` / `production` |
| `LOG_LEVEL` | no | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `DEFAULT_LLM_MODE` | no | 預設模式，預設為 `free` |
| `DAILY_CAP_TOKENS_FREE` | no | 每位使用者每日免費 token 上限 |
| `LLM_RATE_LIMIT_PER_MINUTE` | no | 預留設定，執行層尚未強制限制 |
| `LLM_TIMEOUT_SECONDS` | no | 單次 LLM 呼叫 timeout |
| `RENDER_EXTERNAL_HOSTNAME` | no | Render keep-alive 用公開 hostname |

範例請參考 `.env.example`。

## 測試與品質檢查

```bash
pytest
ruff check .
black . --check
mypy src
```

常用局部測試：

```bash
pytest tests/unit/test_article_mode.py -q
pytest tests/unit/test_mode_switch.py tests/unit/test_webhook_postback.py -q
pytest tests/unit/test_webhook_word_lookup.py tests/unit/test_practice_service.py -q
```

## 資料治理與隱私

- LINE user ID 不直接落地，會先經過 salt + hash
- 使用 soft delete，避免直接硬刪除造成追蹤困難
- 查詢與刪除都會驗證資料 ownership
- API 用量、model、token、latency 會以 trace 形式記錄
- 支援使用者透過 `刪除 <keyword>` 或 `清空資料` 管理自己的資料

## 專案結構

```text
src/
  api/            FastAPI router 與 webhook handler
  services/       指令、抽取、練習、統計、刪除等服務
  repositories/   SQLAlchemy data access
  models/         ORM models
  schemas/        Pydantic schemas
  lib/            LINE / LLM / security / normalizer
  prompts/        LLM prompts
  templates/      LINE 回覆模板
tests/
  unit/           單元測試
  integration/    主要流程整合測試
alembic/          資料庫 migration
docs/             補充文件
```

## 相關文件

以下文件可作為補充參考；若內容與本 README 或目前程式行為不一致，請以本 README 與程式碼為準。

- `docs/developer-feature-command-guide.md`
- `docs/edge-cases.md`
- `docs/deployment.md`
- `specs/001-line-jp-learning/spec.md`
- `specs/001-line-jp-learning/data-model.md`
- `specs/001-line-jp-learning/quickstart.md`
