# Quickstart Guide: LINE 日語學習助教 Bot

**Feature ID**: `001-line-jp-learning`  
**Date**: 2026-01-27

---

## Prerequisites

Before starting development, ensure you have:

1. **Python 3.11+** installed
2. **LINE Developer Account** with Messaging API channel
3. **Supabase Account** (free tier sufficient for MVP)
4. **OpenAI API Key** with GPT-4o-mini access

---

## Step 1: Project Setup

```bash
# Clone repository
cd c:\Users\user\Workspace\projects\japanese-learning

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies (after creating requirements.txt)
pip install -r requirements.txt
```

---

## Step 2: Environment Configuration

Create `.env` file in project root:

```env
# LINE
LINE_CHANNEL_ACCESS_TOKEN=your_channel_access_token
LINE_CHANNEL_SECRET=your_channel_secret

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:port/db

# OpenAI
OPENAI_API_KEY=sk-your-api-key

# App
APP_ENV=development
LOG_LEVEL=DEBUG
```

---

## Step 3: LINE Bot Setup

1. Go to [LINE Developers Console](https://developers.line.biz/)
2. Create a new Messaging API channel
3. Note down:
   - Channel ID
   - Channel Secret
   - Channel Access Token (issue long-lived token)
4. Set Webhook URL: `https://your-domain/webhook`
5. Enable "Use webhook"
6. Disable "Auto-reply messages" and "Greeting messages"

---

## Step 4: Database Setup

### Option A: Supabase (Recommended)

1. Create new project at [supabase.com](https://supabase.com)
2. Go to Settings - Database - Connection string
3. Copy the URI (use connection pooler for production)
4. Run migrations:

```bash
# Using Alembic
alembic upgrade head
```

### Option B: Local PostgreSQL

```bash
# Create database
createdb jp_learning_dev

# Run migrations
alembic upgrade head
```

---

## Step 5: Run Development Server

```bash
# Start FastAPI server
uvicorn src.main:app --reload --port 8000

# Expose local server (for LINE webhook)
# Option 1: ngrok
ngrok http 8000

# Option 2: VS Code port forwarding
# Use VS Code's built-in port forwarding feature
```

---

## Step 6: Verify Setup

### Test Webhook

```bash
# Health check
curl http://localhost:8000/health

# Expected response
{"status": "ok"}
```

### Test LINE Connection

1. Add your bot as friend via QR code
2. Send "隱私" command
3. Should receive privacy policy response

---

## Project Structure

```
japanese-learning/
├── src/
│   ├── main.py              # FastAPI entry
│   ├── config.py            # Settings
│   ├── api/
│   │   └── webhook.py       # LINE webhook handler
│   ├── services/
│   │   ├── command_service.py
│   │   ├── router_service.py
│   │   ├── extractor_service.py
│   │   └── practice_service.py
│   ├── repositories/
│   │   ├── raw_message_repo.py
│   │   ├── document_repo.py
│   │   ├── item_repo.py
│   │   └── practice_log_repo.py
│   ├── models/
│   │   ├── raw_message.py
│   │   ├── document.py
│   │   ├── item.py
│   │   └── practice_log.py
│   ├── schemas/
│   │   ├── router.py
│   │   ├── extractor.py
│   │   └── practice.py
│   └── lib/
│       ├── normalizer.py
│       ├── line_client.py
│       └── llm_client.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── alembic/
│   └── versions/
├── specs/
│   └── 001-line-jp-learning/
├── .env
├── .env.example
├── requirements.txt
├── alembic.ini
└── README.md
```

---

## Key Dependencies

```
# requirements.txt
fastapi>=0.109.0
uvicorn>=0.27.0
line-bot-sdk>=3.5.0
openai>=1.10.0
sqlalchemy>=2.0.25
asyncpg>=0.29.0
alembic>=1.13.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
python-dotenv>=1.0.0
jaconv>=0.3.4
pytest>=7.4.0
pytest-asyncio>=0.23.0
httpx>=0.26.0
```

---

## Development Commands

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=src

# Format code
black src tests
isort src tests

# Type check
mypy src

# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1
```

---

## Next Steps

After setup is complete:

1. Implement models and migrations (Task 1-2)
2. Implement command service (Task 3)
3. Implement router service (Task 4)
4. Continue with tasks.md sequence

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| LINE webhook verification fails | Check signature validation, ensure correct channel secret |
| Database connection error | Verify DATABASE_URL, check Supabase connection pooler settings |
| OpenAI rate limit | Implement exponential backoff, check API usage dashboard |
| Japanese encoding issues | Ensure UTF-8 encoding throughout, use jaconv for normalization |

---

## Resources

- [LINE Messaging API Docs](https://developers.line.biz/en/docs/messaging-api/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 Tutorial](https://docs.sqlalchemy.org/en/20/tutorial/)
- [OpenAI API Reference](https://platform.openai.com/docs/api-reference)
- [Supabase Docs](https://supabase.com/docs)
