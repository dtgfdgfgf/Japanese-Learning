# LINE 日語學習助教 Bot 📚

**Feature ID:** `001-line-jp-learning`  
**Created:** 2026-01-26  
**Status:** In Progress → MVP Ready

## 功能描述

一個透過 LINE Messaging API 運作的日語學習助手，幫助使用者：
- 📥 **入庫**: 保存日文學習素材（文章、句子、單字列表）
- 🔍 **分析**: 使用 AI 自動抽取單字和文法
- 📝 **練習**: 根據已入庫的內容產生練習題
- ✅ **判分**: 自動批改答案並追蹤學習進度
- 🔎 **查詢**: 搜尋已入庫的單字和文法
- 🗑️ **刪除**: 管理和清理學習資料
- 🔒 **隱私**: 查看資料保存與使用說明

## 快速開始

### 環境需求

- Python 3.11+
- PostgreSQL (Supabase)
- LINE Messaging API Channel
- Anthropic API Key (主要 LLM)
- Google Gemini API Key (免費模式，選用)

### 安裝步驟

```bash
# 1. Clone 專案
git clone <repository-url>
cd japanese-learning

# 2. 建立虛擬環境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# 3. 安裝依賴
pip install -e .

# 4. 設定環境變數
cp .env.example .env
# 編輯 .env 填入你的設定

# 5. 執行資料庫遷移
alembic upgrade head

# 6. 啟動服務
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### 環境變數設定

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db

# LINE
LINE_CHANNEL_SECRET=your_channel_secret
LINE_CHANNEL_ACCESS_TOKEN=your_access_token

# LLM
ANTHROPIC_API_KEY=sk-ant-xxx
GEMINI_API_KEY=your_gemini_key  # 選用，免費模式使用

# Security
USER_ID_SALT=random_secure_string
```

### LINE Bot 設定

1. 前往 [LINE Developers Console](https://developers.line.biz/)
2. 建立 Messaging API Channel
3. 取得 Channel Secret 和 Channel Access Token
4. 設定 Webhook URL: `https://your-domain.com/webhook`
5. 啟用 Webhook

## 指令列表

| 指令 | 說明 | 範例 |
|------|------|------|
| `入庫` | 保存前一則訊息 | 貼上日文後輸入「入庫」|
| `分析` | 分析待處理的素材 | 入庫後輸入「分析」|
| `練習` | 開始練習（5題）| 直接輸入「練習」|
| `查詢 <詞>` | 搜尋單字或文法 | 「查詢 考える」|
| `刪除最後一筆` | 刪除最近一筆 | 直接輸入 |
| `清空資料` | 刪除所有資料 | 需二次確認 |
| `說明` | 顯示使用說明 | 直接輸入 |
| `隱私` | 顯示隱私政策 | 直接輸入 |

## 專案結構

```
japanese-learning/
├── src/
│   ├── api/              # API endpoints
│   │   └── webhook.py    # LINE webhook handler
│   ├── lib/              # 共用函式庫
│   │   ├── llm_client.py # LLM 客戶端（mode-based）
│   │   ├── line_client.py# LINE API 客戶端
│   │   ├── normalizer.py # 日文正規化
│   │   └── security.py   # 安全相關函數
│   ├── models/           # SQLAlchemy models
│   ├── prompts/          # LLM prompt templates
│   ├── repositories/     # 資料庫操作層
│   ├── schemas/          # Pydantic schemas
│   ├── services/         # 業務邏輯層
│   ├── templates/        # 訊息模板
│   ├── config.py         # 設定管理
│   ├── database.py       # 資料庫連線
│   └── main.py           # FastAPI app
├── tests/
│   ├── fixtures/         # 測試資料
│   ├── integration/      # 整合測試
│   └── unit/             # 單元測試
├── alembic/              # 資料庫遷移
├── specs/                # 功能規格文件
└── docs/                 # 文件
```

## 技術架構

- **Web Framework**: FastAPI
- **Database**: PostgreSQL (Supabase) + SQLAlchemy 2.0
- **LLM**: Anthropic Claude (主) / Google Gemini (免費模式)
- **LINE SDK**: line-bot-sdk v3
- **日文處理**: jaconv

## 開發指令

```bash
# 執行測試
pytest

# 程式碼檢查
ruff check .
black --check .

# 格式化
black .
ruff check --fix .

# 執行遷移
alembic upgrade head
alembic downgrade -1
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
3. 設定 Start Command: `uvicorn src.main:app --host 0.0.0.0 --port $PORT`
4. 部署後更新 LINE Webhook URL

## 相關文件

- [功能規格](specs/001-line-jp-learning/spec.md)
- [技術計劃](specs/001-line-jp-learning/plan.md)
- [任務清單](specs/001-line-jp-learning/tasks.md)
- [部署指南](docs/deployment.md)

## License

MIT
