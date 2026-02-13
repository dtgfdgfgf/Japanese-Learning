# Copilot Instructions: LINE 日語學習助教 Bot

<!-- 
  PROJECT CONSTITUTION v1.1.0
  Feature ID: 001-line-jp-learning
  Last Updated: 2026-01-29
  
  This file provides AI assistants (GitHub Copilot, Claude, etc.) with project-specific context.
  Place in .github/ for VS Code Copilot to auto-detect.
-->

---

## 📋 Project Overview

**Name**: LINE 日語學習助教 Bot (`line-jp-learning`)  
**Type**: LINE Messaging API Bot  
**Description**: 透過 LINE 完成「素材入庫 → 結構化分析 → 練習複習」完整循環的個人化日語學習助手

**Core User Flow**:
1. 使用者貼上日文素材 → 輸入「入庫」保存
2. 輸入「分析」→ LLM 結構化抽取 vocab/grammar items
3. 輸入「練習」→ 系統出題、使用者作答、系統判分

**Spec Reference**: `specs/001-line-jp-learning/spec.md`

---

## 🛠 Technology Stack

| Category | Technology | Version | Notes |
|----------|------------|---------|-------|
| Language | Python | 3.11+ | Async/await, type hints required |
| Framework | FastAPI | ≥0.109.0 | Async endpoints, Pydantic validation |
| Database | PostgreSQL | 15+ | Via Supabase, JSONB for flexible payload |
| ORM | SQLAlchemy | 2.0+ | Async mode with `asyncpg` driver |
| Migration | Alembic | ≥1.13.0 | Autogenerate from models |
| LLM Primary | Anthropic Claude | Sonnet / Opus | Mode-based selection, structured JSON output |
| LLM Free | Google Gemini | gemini-3-pro-preview | Free mode provider |
| LINE SDK | line-bot-sdk | ≥3.5.0 | Official Python SDK |
| Testing | pytest | ≥8.0.0 | pytest-asyncio for async tests |
| Linting | ruff | ≥0.2.0 | Fast Python linter |
| Formatting | black | ≥24.1.0 | Line length: 88 |

---

## 📁 Project Structure

```
japanese-learning/
├── src/
│   ├── main.py              # FastAPI app entry, health endpoint
│   ├── config.py            # Pydantic Settings (env vars)
│   ├── database.py          # SQLAlchemy async engine & session
│   │
│   ├── api/
│   │   ├── webhook.py       # LINE webhook handler (POST /webhook)
│   │   └── middleware.py    # Error handling, request_id logging
│   │
│   ├── models/              # SQLAlchemy ORM models
│   │   ├── raw_message.py   # 原始訊息 (immutable)
│   │   ├── document.py      # 文件 (parsed/deferred/failed)
│   │   ├── item.py          # 學習單元 (vocab/grammar)
│   │   └── practice_log.py  # 練習紀錄
│   │
│   ├── repositories/        # Data access layer (CRUD)
│   │   ├── base.py          # Generic BaseRepository[ModelT]
│   │   ├── raw_message_repo.py
│   │   ├── document_repo.py
│   │   ├── item_repo.py
│   │   └── practice_log_repo.py
│   │
│   ├── services/            # Business logic layer
│   │   ├── command_service.py    # 指令解析 + dispatch
│   │   ├── router_service.py     # LLM 意圖分類 (fallback)
│   │   ├── extractor_service.py  # LLM 內容抽取
│   │   ├── practice_service.py   # 出題、判分、item 選取
│   │   ├── session_service.py    # 練習 session state
│   │   └── delete_service.py     # 刪除邏輯
│   │
│   ├── schemas/             # Pydantic schemas (API/LLM)
│   │   ├── command.py       # CommandType, ParsedCommand
│   │   ├── extractor.py     # ExtractorRequest/Response
│   │   └── practice.py      # PracticeQuestion, PracticeSession
│   │
│   ├── prompts/             # LLM prompt templates
│   │   ├── router.py        # 意圖分類 prompt
│   │   └── extractor.py     # 內容抽取 prompt
│   │
│   ├── lib/                 # Utilities
│   │   ├── llm_client.py    # Anthropic + Gemini (mode-based)
│   │   ├── line_client.py   # LINE SDK wrapper
│   │   ├── normalizer.py    # Japanese text normalization
│   │   └── security.py      # User ID hashing
│   │
│   └── templates/           # Response templates
│
├── tests/
│   ├── conftest.py          # Fixtures, mock session
│   ├── fixtures/            # JSON test data (Japanese samples)
│   ├── unit/                # Unit tests (mock dependencies)
│   └── integration/         # Integration tests (DB, API)
│
├── alembic/
│   ├── env.py               # Migration environment
│   └── versions/            # Migration scripts
│
├── specs/001-line-jp-learning/
│   ├── spec.md              # Feature specification
│   ├── plan.md              # Technical plan
│   ├── tasks.md             # Task decomposition
│   ├── data-model.md        # Entity definitions
│   └── quickstart.md        # Setup guide
│
├── pyproject.toml           # Project config, dependencies
├── requirements.txt         # Pip dependencies
├── alembic.ini              # Alembic config
├── Dockerfile               # Container build
└── docker-compose.yml       # Local dev stack
```

---

## 🏗 Architecture Patterns

### Layered Architecture

```
┌─────────────────────────────────────────┐
│  Presentation Layer (src/api/)          │
│  - LINE Webhook receives messages       │
│  - Signature validation                 │
│  - Response formatting                  │
├─────────────────────────────────────────┤
│  Application Layer (src/services/)      │
│  - CommandService: parse & dispatch     │
│  - RouterService: LLM intent classify   │
│  - ExtractorService: LLM extraction     │
│  - PracticeService: quiz generation     │
├─────────────────────────────────────────┤
│  Domain Layer (src/models/, schemas/)   │
│  - Entities: RawMessage, Document, Item │
│  - Business rules in services           │
├─────────────────────────────────────────┤
│  Infrastructure Layer                   │
│  - Repositories (src/repositories/)     │
│  - LLM Client (src/lib/llm_client.py)   │
│  - LINE Client (src/lib/line_client.py) │
└─────────────────────────────────────────┘
```

### Key Design Decisions

1. **Command-first routing**: 硬規則指令（入庫、分析、練習）優先，fallback 到 LLM Router
2. **Soft delete**: 所有刪除操作設置 `is_deleted=True`，不物理刪除
3. **Deferred parsing**: 長文先存 raw，分析時再處理
4. **LLM mode-based**: 依據模式選擇 provider — free→Gemini, cheap→Sonnet, rigorous→Opus
5. **User ID hashing**: 不直接儲存 LINE user ID，使用 SHA-256 + salt

---

## 📊 Data Model

### Core Entities

| Entity | Table | Description |
|--------|-------|-------------|
| RawMessage | `raw_messages` | 使用者原始輸入 (immutable) |
| Document | `documents` | 入庫文件 (parse_status: parsed/deferred/failed) |
| Item | `items` | 學習單元 (vocab/grammar)，JSONB payload |
| PracticeLog | `practice_logs` | 練習紀錄 (is_correct, score) |

### Entity Relationships

```
User (LINE) ─┬─ raw_messages (1:N)
             │       └─ documents (1:1)
             │              └─ items (1:N)
             │
             └─ practice_logs (1:N)
                    └─ items (N:1)
```

### Item Deduplication

- Unique constraint: `(user_id, item_type, key) WHERE is_deleted = FALSE`
- Key format:
  - Vocab: `vocab:<normalized_surface>`
  - Grammar: `grammar:<normalized_pattern>`

### Upsert Pattern

**Item upsert 使用「先查後決定」模式：**

1. 以 `get_by_unique_key(user_id, item_type, key)` 查詢現有 item
2. 若存在 → 更新 `payload`、`confidence`、`source_quote`
3. 若不存在 → 建立新 item

⚠️ **注意**：此模式在高並發下有 race condition 風險，但 MVP 階段（單使用者）可接受。

### Payload Schemas

**Vocab** (JSONB):
```json
{
  "surface": "考える",
  "reading": "かんがえる",
  "pos": "verb",
  "glossary_zh": ["思考", "考慮"],
  "example_ja": "もう少し考えてみます。",
  "example_zh": "我再想想看。",
  "level": "N3"
}
```

**Grammar** (JSONB):
```json
{
  "pattern": "〜てしまう",
  "meaning_zh": "表示遺憾/不小心做了…",
  "usage": ["常見語感是『不小心』或『遺憾』"],
  "form_notes": "Vて + しまう",
  "example_ja": "財布を忘れてしまった。"
}
```

---

## 🎮 Commands Reference

### 硬規則指令（regex 精確匹配，confidence=1.0）

| Command | Trigger Pattern | Description |
|---------|----------------|-------------|
| `入庫` | `^入庫$` | 保存 `last_message` 為素材（raw_message + document deferred） |
| `<單字> save` | `^(.+)\s+save$` | 直接入庫指定單字（例：`鋭い save`） |
| `1` | `^1$` | 確認入庫（pending_save 流程）或選擇刪除項目（pending_delete 流程） |
| `分析` | `^分析$` | 對最近一筆 deferred 文件執行 LLM Extractor |
| `練習` | `^練習$` | 從 items 出 5 題（priority: 新增 > 高錯誤率 > 久未練 > 隨機） |
| `結束練習` / `停止練習` | `^(結束練習\|停止練習)$` | 中途結束當前練習 session |
| `查詢 <keyword>` | `^查詢\s+(.+)$` | 搜尋 vocab/grammar（surface/reading/pattern） |
| `查詢` | `^查詢$` | 缺少關鍵字時顯示提示 |
| `刪除 <keyword>` | `^刪除\s+(.+)$` | 搜尋並刪除指定 item（1 筆直接刪，2-5 筆列表選擇，>5 筆請更精確） |
| `刪除` | `^刪除$` | 缺少關鍵字時顯示提示 |
| `清空資料` | `^清空資料$` | 設置確認狀態，等待二次確認（60 秒 TTL） |
| `確定清空資料` | `^確定清空資料$` | 二次確認後軟刪除使用者所有資料 |
| `說明` / `幫助` / `help` | `^(說明\|幫助\|help)$` | 顯示所有可用指令 |
| `用量` / `cost` | `^(用量\|cost)$` | 查詢 API 用量（本月 + 累計，按 model 分組） |
| `統計` / `進度` | `^(統計\|進度)$` | 查詢學習進度（素材數、練習數、正確率、7 日趨勢） |
| `免費模式` / `便宜模式` / `嚴謹模式` | `^(免費模式\|便宜模式\|嚴謹模式)$` | 切換 LLM 模式 |
| `切換免費` / `切換便宜` / `切換嚴謹` | `^切換(免費\|便宜\|嚴謹)$` | 切換 LLM 模式（另一種觸發方式） |
| `英文` / `日文` | `^(英文\|日文)$` | 切換學習目標語言 |
| `隱私` | `^隱私$` | 顯示隱私政策 |

### Dispatch 狀態守衛

Pre-dispatch 階段依序檢查 `pending_delete` → `pending_save` → `has_session`，符合條件則優先處理對應邏輯。

**PENDING_SAFE_COMMANDS**（不中斷 pending 狀態的安全指令）：
`HELP`, `MODE_SWITCH`, `SET_LANG`, `COST`, `STATS`, `PRIVACY`, `EXIT_PRACTICE`, `WORD_SAVE`

### LLM Router Fallback（UNKNOWN 指令）

未匹配硬規則時，經過 edge case 過濾後交由 `RouterService.classify()` 進行 LLM 意圖分類，支援 intent：`save`, `analyze`, `practice`, `search`, `delete`, `help`, `chat`, `unknown`。

---

## 💻 Code Style Guidelines

### Python Conventions

- **Type hints required**: All function signatures must have type annotations
- **Async by default**: Use `async def` for I/O operations
- **Docstrings**: Google style, include Args/Returns/Raises
- **Line length**: 88 characters (black default)
- **Import order**: stdlib → third-party → local (ruff I)

### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Module | snake_case | `command_service.py` |
| Class | PascalCase | `CommandService` |
| Function | snake_case | `parse_command()` |
| Variable | snake_case | `user_id` |
| Constant | UPPER_SNAKE | `COMMAND_PATTERNS` |
| Type Alias | PascalCase | `ItemType` |

### Repository Pattern

```python
class ItemRepository(BaseRepository[Item]):
    model = Item
    pk_field = "item_id"
    
    async def get_by_user(self, user_id: str) -> list[Item]:
        # Custom queries go here
        ...
```

### Service Pattern

```python
class ExtractorService:
    def __init__(self, session: AsyncSession, llm_client: LLMClient):
        self.item_repo = ItemRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.llm = llm_client
    
    async def extract(self, doc_id: str) -> ExtractorResponse:
        # Business logic orchestration
        ...
```

### Error Handling

```python
# Use custom exceptions for business logic errors
from src.exceptions import NoContentToSaveError, InsufficientItemsError

# Catch at service boundary, transform to user-friendly message
try:
    result = await service.process()
except NoContentToSaveError:
    return "請先貼上要入庫的內容"
```

### Communication Language

**All AI assistant responses must be in Traditional Chinese (繁體中文).**
- 所有回應、解釋、與使用者的溝通必須使用繁體中文
- 不使用簡體中文（简体中文）
- 無標準翻譯的技術術語可保留英文

### Comment Language

- **所有新增程式碼註解必須使用繁體中文**（現有英文註解不強制修改）
- Docstrings 使用 Google style，內容可為中英混合（參數名保留英文）

```python
async def extract_items(doc_id: str) -> list[Item]:
    """從文件中抽取學習單元。
    
    Args:
        doc_id: 文件 UUID
        
    Returns:
        抽取出的 vocab/grammar items 列表
        
    Raises:
        DocumentNotFoundError: 找不到指定文件
    """
    ...
```

---

## 📐 Minimal Code Changes Principle

**關鍵原則**：修改或新增程式碼時，遵循最小變更原則。

### Philosophy

- 只做達成功能所需的最小變更
- 盡可能保留現有程式碼結構與模式
- 只修改必要的部分來修復 bug 或新增功能
- 尊重現有架構與設計決策

### 這不代表犧牲品質

- 維持適當的錯誤處理與資源管理
- 遵循本憲章所有其他規範
- 必要時進行重構以確保正確性或關鍵可維護性
- 新功能從一開始就要有適當的架構設計

### Practical Application

| 情境 | 做法 |
|------|------|
| **Bug 修復** | 只修改造成問題的特定行 |
| **新功能** | 整合到現有模式，而非重寫周圍程式碼 |
| **參數新增** | 新增欄位而不重構現有資料流 |
| **效能改善** | 針對特定瓶頸優化，而非整個子系統 |
| **重構** | 只在程式碼壞掉、無法維護、或有風險時才進行 |

---

## 📝 Code Change Communication

**提出或執行程式碼變更時，必須提供以下資訊：**

1. **Precise Location**: 檔案路徑、class 名稱、function 名稱、行號範圍
2. **Clear Rationale**: 為何需要此變更（bug fix / new feature / performance / safety）
3. **Change Scope**: 什麼會被修改、什麼不會被修改
4. **Impact Assessment**: 哪些元件 / 流程會受影響

### Example Format

```
Location: src/services/extractor_service.py:87 in extract() method
Reason: LLM timeout 時缺少錯誤處理，導致未捕獲例外
Change: 新增 try-except 區塊並 fallback 至 OpenAI (lines 87-95)
Impact: 只影響 extraction 流程；不影響 practice 或 save 操作
```

### 這確保了

- 實作前清楚理解變更內容
- 最小化意外修改
- 更好的 review 與 debug 能力
- 變更歷史有文件記錄

---

## 🧪 Testing Guidelines

### Test Structure

```
tests/
├── conftest.py              # Shared fixtures
├── fixtures/
│   ├── japanese_samples.json  # Real Japanese test data
│   └── extractor/           # LLM response mocks
├── unit/
│   ├── test_command_service.py
│   ├── test_extractor_service.py
│   └── test_normalizer.py
└── integration/
    ├── test_save.py         # Full webhook flow
    └── test_analyze.py      # DB + service integration
```

### Testing Conventions

```python
# Unit test: mock external dependencies
@pytest.mark.asyncio
async def test_parse_command_save():
    result = parse_command("入庫")
    assert result.command_type == CommandType.SAVE
    assert result.confidence == 1.0

# Integration test: use test database
@pytest.mark.asyncio
async def test_save_flow(db_session, mock_line_client):
    service = CommandService(db_session)
    result = await service.handle_save("user123", "考える")
    assert result.doc_id is not None
```

### Mock Patterns

```python
# Mock LLM responses
@pytest.fixture
def mock_llm_client():
    client = AsyncMock(spec=LLMClient)
    client.complete.return_value = LLMResponse(
        content='{"items": [...]}',
        model="claude-sonnet-4-20250514",
        ...
    )
    return client
```

---

## 🚀 Development Commands

### Setup

```bash
# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Unix

# Install dependencies
pip install -e ".[dev]"
```

### Database

```bash
# Run migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"

# Rollback
alembic downgrade -1
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test
pytest tests/unit/test_command_service.py -v
```

### Code Quality

```bash
# Lint
ruff check .

# Format
black .

# Type check
mypy src
```

### Server

```bash
# Development server
uvicorn src.main:app --reload --port 8000

# Production
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

---

## � Deployment

**詳細部署指南**：參見 `docs/deployment.md`

### 支援平台

| 平台 | 說明 |
|------|------|
| Railway | 推薦，自動部署 |
| Render | 免費方案可用 |
| Docker (self-hosted) | 完整控制 |

### 生產環境注意事項

- 使用多 workers：`uvicorn src.main:app --workers 4`
- 確保 `APP_ENV=production`
- 資料庫使用 connection pooler（Supabase 內建）
- 設定適當的 `LOG_LEVEL`（建議 `INFO` 或 `WARNING`）

---

## �🔧 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LINE_CHANNEL_ACCESS_TOKEN` | Yes | LINE Channel Access Token |
| `LINE_CHANNEL_SECRET` | Yes | LINE Channel Secret |
| `DATABASE_URL` | Yes | PostgreSQL asyncpg connection string |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API Key |
| `GEMINI_API_KEY` | No | Google Gemini API Key (free mode) |
| `USER_ID_SALT` | Yes | Salt for hashing user IDs (min 32 chars) |
| `APP_ENV` | No | `development` / `staging` / `production` |
| `LOG_LEVEL` | No | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

---

## ⚠️ Important Constraints

### Performance

- **P95 response time**: < 3 seconds for practice commands
- **LLM timeout**: 15 seconds
- **LINE reply timeout**: 30 seconds max
- **Max items per user**: 1000 items without degradation

### Security

- Never store raw LINE user IDs - always use `hash_user_id()`
- Validate LINE webhook signature before processing
- Sanitize user input before LLM prompts

### LLM Usage

- Use structured JSON output mode for reliable parsing
- Include confidence scores in extraction results
- Log all LLM traces for debugging (`llm_trace` JSONB field)
- Minimize API calls - cache common patterns where possible

### Database

- Always use async session: `async with get_session() as session:`
- Soft delete only: set `is_deleted=True`, never `DELETE`
- Use JSONB for flexible payloads (vocab/grammar schemas)

### Resource Management

**Async 資源必須正確關閉，避免 connection leak 或 resource exhaustion。**

| 資源類型 | 正確做法 |
|---------|----------|
| `AsyncSession` | 使用 `async with get_session() as session:` |
| `httpx.AsyncClient` | 使用 `async with httpx.AsyncClient() as client:` 或確保 `await client.aclose()` |
| `LLMClient` | 使用 `get_llm_client()` 取得 singleton，SDK 內部管理連線池 |
| File handles | 使用 `async with aiofiles.open()` |

```python
# 正確：使用 context manager
async with get_session() as session:
    repo = ItemRepository(session)
    items = await repo.get_by_user(user_id)

# 錯誤：忘記關閉 session
session = async_session_factory()
items = await session.execute(query)  # session 未關閉！
```

---

## ⚡ Common Pitfalls

**開發本專案時常見的陷阱與避免方式：**

| # | 陷阱 | 後果 | 正確做法 |
|---|------|------|----------|
| 1 | **未正確使用 async session** | Connection pool exhaustion | 使用 `async with get_session()` context manager |
| 2 | **查詢時忘記 soft delete 條件** | 回傳已刪除資料 | 所有查詢加上 `WHERE is_deleted = FALSE` |
| 3 | **缺少 type hints** | 型別錯誤難以追蹤 | 所有 function 必須有完整 type annotations |
| 4 | **直接呼叫 LLM 無 timeout** | 請求卡住導致 LINE timeout | 使用 `LLMClient` 內建 timeout |
| 5 | **儲存原始 LINE user ID** | 隱私風險 | 一律使用 `hash_user_id()` |
| 6 | **缺少 webhook signature 驗證** | 安全漏洞 | 使用 `LineClient.verify_signature()` |
| 7 | **LLM token 使用無上限** | 成本失控 | 請求時設定 `max_tokens` |
| 8 | **在 async function 中使用 blocking 呼叫** | Event loop 阻塞 | 使用 async 版本的 library 或 `run_in_executor` |
| 9 | **Item upsert 邏輯錯誤** | 重複資料或遺失更新 | 依 `(user_id, item_type, key)` 正確 upsert |
| 10 | **未處理 LLM JSON parse 失敗** | 未捕獲例外導致 500 | 加上 try-except 並記錄 `llm_trace` |

---

## 🔍 When Reviewing Code, Focus On

**Code Review 時的檢查重點與優先級。**

### 1. Async/Await Correctness (Critical)

- [ ] 所有 I/O 操作使用 `async def` 與 `await`
- [ ] Async function 中無 blocking 呼叫（如 `time.sleep`、sync `requests`）
- [ ] Session lifecycle 使用 `async with` 正確管理
- [ ] 無 `await` 遺漏導致 coroutine 未執行

### 2. Database Patterns (Critical)

- [ ] 所有查詢尊重 soft delete（`is_deleted = FALSE`）
- [ ] Async session 正確關閉
- [ ] 多表操作使用 transaction
- [ ] Upsert 邏輯依 unique constraint 正確實作

### 3. Type Safety (Important)

- [ ] 所有 function signatures 有 type hints
- [ ] Pydantic models 用於 validation
- [ ] Optional types 有適當的 null check
- [ ] 使用 `TypeVar` 與 `Generic` 維持型別一致性

### 4. Error Handling (Important)

- [ ] Business exceptions 適當定義與 raise
- [ ] LLM 呼叫有 timeout
- [ ] 回傳使用者友善的錯誤訊息
- [ ] Exception 有適當 logging（含 context）

### 5. Security (Critical)

- [ ] User IDs 儲存前一律 hash
- [ ] Webhook signature 已驗證
- [ ] 使用者輸入送入 LLM 前已 sanitize
- [ ] 無敏感資訊 hardcode 或 log

### 6. Code Quality (Required)

- [ ] 新增程式碼註解使用繁體中文
- [ ] 遵循最小變更原則
- [ ] Google-style docstrings 存在
- [ ] Import order 正確（stdlib → third-party → local）

### 7. LLM Integration (Important)

- [ ] 使用 structured JSON output mode
- [ ] 設定 `max_tokens` 防止成本失控
- [ ] 記錄 `llm_trace` 供 debug
- [ ] Confidence threshold 有適當處理

---

### Review Priority

| 等級 | 定義 | 範例 |
|------|------|------|
| **P0 (Reject)** | 安全漏洞、資料外洩、blocking async | 未驗證 webhook signature、儲存原始 user ID |
| **P1 (Must fix)** | 缺少 type hints、錯誤處理不足、資源未關閉 | 缺少 return type、session 未 close |
| **P2 (Should fix)** | 缺少 docstrings、註解語言錯誤、效能次佳 | 英文註解、未使用 index |
| **P3 (Nice to have)** | 小型 style 問題、優化機會 | 變數命名可更清楚 |

---

## 📚 Reference Documents

| Document | Location | Purpose |
|----------|----------|---------|
| Spec | `specs/001-line-jp-learning/spec.md` | Feature requirements |
| Plan | `specs/001-line-jp-learning/plan.md` | Technical architecture |
| Tasks | `specs/001-line-jp-learning/tasks.md` | Task breakdown |
| Data Model | `specs/001-line-jp-learning/data-model.md` | Entity definitions |
| Quickstart | `specs/001-line-jp-learning/quickstart.md` | Setup guide |

---

## 🔄 Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.2.0 | 2026-01-29 | 修正版本號、移除 AI 標記規範、修正 LLMClient 說明、補充 Upsert Pattern、新增 Deployment section |
| 1.1.0 | 2026-01-29 | 新增 Code Style Requirements、Minimal Code Changes、Code Change Communication、Resource Management、Common Pitfalls、Code Review Checklist |
| 1.0.0 | 2026-01-29 | Initial constitution based on SDD documents |
