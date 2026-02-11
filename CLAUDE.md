# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LINE 日語學習助教 Bot — 透過 LINE Messaging API 完成「素材入庫 → LLM 結構化分析 → 練習複習」完整循環的個人化日語學習助手。

Tech stack: Python 3.11+ / FastAPI / SQLAlchemy 2.0 async (asyncpg) / PostgreSQL / Alembic / Anthropic Claude + Google Gemini (mode-based) / LINE Bot SDK v3

## Common Commands

```bash
# 安裝依賴（含開發工具）
pip install -e ".[dev]"

# 開發伺服器（hot reload）
uvicorn src.main:app --reload --port 8000

# 執行所有測試
pytest

# 執行單一測試檔
pytest tests/unit/test_command_service.py -v

# 執行 integration tests
pytest tests/integration/ -v

# Coverage
pytest --cov=src --cov-report=html

# Lint / Format / Type check
ruff check .
black .
mypy src

# 資料庫 migration
alembic upgrade head
alembic revision --autogenerate -m "description"
alembic downgrade -1

# Docker 本地開發
docker-compose up -d
docker-compose exec app alembic upgrade head
```

## Architecture

分層架構，指令路由採「硬規則優先 → LLM Router fallback」策略：

```
Presentation (src/api/)        → LINE webhook, signature validation
Application  (src/services/)   → CommandService, RouterService, ExtractorService, PracticeService
Domain       (src/models/, schemas/) → ORM entities, Pydantic schemas
Infrastructure (src/repositories/, lib/) → BaseRepository[T] CRUD, LLMClient, LineClient
```

**指令流程**: 使用者訊息 → `webhook.py` → `CommandService.parse_command()` regex 匹配 → 未匹配則 `RouterService` LLM 意圖分類 → 分派至對應 service

**Dispatch 狀態守衛**: pre-dispatch 階段依序檢查 `pending_delete` → `pending_save` → `has_session`，符合條件則優先處理對應邏輯，不進入一般指令分派。`PENDING_SAFE_COMMANDS`（HELP、MODE_SWITCH、SET_LANG、COST、STATS、PRIVACY）在 pending 狀態下仍可正常執行。

**LLM mode-based 選擇**: 依據模式選擇 provider — free→Gemini 3 Pro, cheap→Claude Sonnet 4.5, rigorous→Claude Opus 4.6。實作在 `src/lib/llm_client.py` 的 `MODE_MODEL_MAP`。

**練習 session**: DB-backed（`PracticeSessionModel` + `SessionService`），JSONB 存放題目狀態，30 分鐘 TTL 自動過期。

**資料流**: `raw_messages` → `documents`（1:1）→ `items`（1:N vocab/grammar，JSONB payload）→ `practice_logs`

**Item 去重**: unique constraint `(user_id, item_type, key) WHERE is_deleted = FALSE`，upsert 採「先查後決定」模式。

## Critical Rules

以下規則來自 `.github/copilot-instructions.md`（Project Constitution），必須嚴格遵守：

- **Soft delete only**: 所有刪除設 `is_deleted=True`，不物理刪除。所有查詢必須加 `WHERE is_deleted = FALSE`
- **User ID hashing**: 不儲存原始 LINE user ID，一律使用 `hash_user_id()`（`src/lib/security.py`）
- **Async 資源管理**: 永遠使用 `async with get_session() as session:`，不可遺漏關閉
- **Type hints**: 所有 function signatures 必須有完整 type annotations（mypy strict mode）
- **LLM 呼叫**: 必須設 `max_tokens`、使用 structured JSON output、記錄 `llm_trace`、有 timeout
- **註解語言**: 所有新增程式碼註解使用繁體中文
- **溝通語言**: 所有回應使用繁體中文（技術術語可保留英文）
- **最小變更原則**: 只做達成功能所需的最小修改，整合到現有模式而非重寫

## Testing

- `pytest-asyncio` 設定 `asyncio_mode="auto"`，async test 不需手動標記
- Unit tests mock 外部依賴（LLM、LINE SDK、DB session）
- Integration tests 使用測試資料庫（`TEST_DATABASE_URL` 或 `SKIP_DB_TESTS` 跳過）
- Test fixtures 在 `tests/fixtures/`（含真實日文素材 JSON）

## Environment Variables

必要：`LINE_CHANNEL_ACCESS_TOKEN`, `LINE_CHANNEL_SECRET`, `DATABASE_URL`, `ANTHROPIC_API_KEY`, `USER_ID_SALT`（min 32 chars）, `GEMINI_API_KEY`（free mode 需要）

選用：`APP_ENV`（development/production）, `LOG_LEVEL`, `LLM_RATE_LIMIT_PER_MINUTE`（預設 10）

參考 `.env.example`。
