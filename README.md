# LINE 日語學習助教 Bot

透過 LINE Messaging API 完成「素材入庫 → LLM 結構化分析 → 練習複習」完整循環的個人化日語學習助手。

## 功能特色

- **入庫**: 保存日文學習素材（文章、句子、單字列表），AI 自動抽取單字與文法
- **練習**: 根據已入庫內容產生練習題，自動批改並追蹤學習進度
- **查詢**: 搜尋已入庫的單字和文法，顯示完整 LLM 分析結果
- **文章閱讀**: 貼入日文文章後逐字查詢，附帶全文翻譯
- **用量統計**: 查看 API 使用量與費用、學習統計
- **隱私保護**: User ID 雜湊儲存，soft delete，完整資料管理

## 技術架構

| 層級 | 技術 |
|------|------|
| Web Framework | FastAPI |
| Database | PostgreSQL + SQLAlchemy 2.0 async (asyncpg) |
| Migration | Alembic |
| LLM | Anthropic Claude (Sonnet / Opus) + Google Gemini (free mode) |
| LINE SDK | line-bot-sdk v3 |
| 日文處理 | jaconv |

### 分層架構

```
Presentation  (src/api/)         → LINE webhook, middleware
Application   (src/services/)    → CommandService, RouterService, ExtractorService, PracticeService...
Domain        (src/models/, schemas/) → ORM entities, Pydantic schemas
Infrastructure(src/repositories/, lib/) → BaseRepository[T], LLMClient, LineClient
Prompts       (src/prompts/)     → LLM prompt templates (router, extractor, grader, article...)
```

**指令路由**: 使用者訊息 → regex 硬規則匹配 → 未匹配則 LLM Router 意圖分類 → 分派至對應 service

**LLM 模式選擇**: free → Gemini, cheap → Claude Sonnet, rigorous → Claude Opus

**資料流**: `raw_messages` → `documents`(1:1) → `items`(1:N vocab/grammar, JSONB payload) → `practice_logs`

## 快速開始

### 環境需求

- Python 3.11+
- PostgreSQL
- LINE Messaging API Channel
- Anthropic API Key
- Google Gemini API Key（free mode 使用）

### 安裝

```bash
# Clone & 建立虛擬環境
git clone <repository-url>
cd japanese-learning
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安裝依賴（含開發工具）
pip install -e ".[dev]"

# 設定環境變數
cp .env.example .env
# 編輯 .env 填入設定

# 資料庫遷移
alembic upgrade head

# 啟動服務
uvicorn src.main:app --reload --port 8000
```

### 環境變數

必要：

| 變數 | 說明 |
|------|------|
| `DATABASE_URL` | PostgreSQL 連線字串 (asyncpg) |
| `LINE_CHANNEL_SECRET` | LINE Channel Secret |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Channel Access Token |
| `ANTHROPIC_API_KEY` | Anthropic API Key |
| `GEMINI_API_KEY` | Google Gemini API Key (free mode) |
| `USER_ID_SALT` | User ID 雜湊鹽值 (min 32 chars) |

選用：`APP_ENV`, `LOG_LEVEL`, `LLM_RATE_LIMIT_PER_MINUTE` (預設 10)

詳見 `.env.example`。

### LINE Bot 設定

1. 前往 [LINE Developers Console](https://developers.line.biz/) 建立 Messaging API Channel
2. 取得 Channel Secret 和 Channel Access Token
3. 設定 Webhook URL: `https://your-domain.com/webhook`
4. 啟用 Webhook

## 指令列表

| 指令 | 說明 | 範例 |
|------|------|------|
| `入庫` | 保存前一則日文訊息 | 貼上日文後輸入「入庫」|
| `分析` | 分析待處理的素材 | 入庫後輸入「分析」|
| `練習` | 開始練習（5題）| 直接輸入「練習」|
| `查詢 <詞>` | 搜尋單字或文法 | 「查詢 考える」|
| `刪除最後一筆` | 刪除最近入庫的素材 | 直接輸入 |
| `清空資料` | 刪除所有資料（需確認）| 直接輸入 |
| `用量` | 查看 API 使用量與費用 | 直接輸入 |
| `統計` | 查看學習統計 | 直接輸入 |
| `模式 <mode>` | 切換 LLM 模式 | 「模式 free」|
| `文章` | 進入文章閱讀模式 | 貼文章後輸入「文章」|
| `完成閱讀` | 結束文章閱讀模式 | 閱讀完畢輸入 |
| `說明` | 顯示使用說明 | 直接輸入 |
| `隱私` | 顯示隱私政策 | 直接輸入 |

## 開發

```bash
# 執行測試
pytest

# 執行單一測試檔
pytest tests/unit/test_command_service.py -v

# Coverage
pytest --cov=src --cov-report=html

# Lint / Format
ruff check .
black .
mypy src

# 資料庫 migration
alembic upgrade head
alembic revision --autogenerate -m "description"
```

## 部署

### Docker

```bash
docker build -t japanese-learning .
docker run -p 8000:8000 --env-file .env japanese-learning
```

### Railway / Render

1. 連結 GitHub repository
2. 設定環境變數
3. Start Command: `uvicorn src.main:app --host 0.0.0.0 --port $PORT`
4. 部署後更新 LINE Webhook URL

## License

MIT
