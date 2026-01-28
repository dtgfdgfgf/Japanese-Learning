# Implementation Plan: LINE 日語學習助教 Bot

**Feature ID**: `001-line-jp-learning`  
**Date**: 2026-01-27  
**Spec**: [spec.md](spec.md)  
**Version**: 1.0.0

---

## Summary

提供一個透過 LINE 即可完成「素材入庫 - 結構化分析 - 練習複習」完整循環的個人化日語學習助手。系統採用 LINE Messaging API 接收使用者訊息，以 LLM 進行意圖判斷與結構化抽取，PostgreSQL 儲存學習素材與練習紀錄。

---

## Technical Context

| Item | Value |
|------|-------|
| **Language/Version** | Python 3.11 |
| **Primary Dependencies** | FastAPI, line-bot-sdk, Anthropic SDK, OpenAI SDK (fallback), SQLAlchemy |
| **Storage** | PostgreSQL 15 (Supabase) |
| **Testing** | pytest, pytest-asyncio |
| **Target Platform** | Linux server (Docker container) |
| **Project Type** | web (API server) |

### Performance Goals

- P95 response time < 3 seconds for practice commands
- Support 1000 items per user without performance degradation

### Constraints

- LINE Messaging API reply timeout: 30 seconds
- LLM API latency: typically 1-3 seconds per call
- Cost control: minimize LLM API calls where possible

### Scale/Scope

- MVP phase: single user initially, expandable to 100 users
- Data volume: up to 1000 items per user

---

## Architecture Overview

The system follows a layered architecture with clear separation of concerns:

1. **Presentation Layer**: LINE Webhook handler receives messages and dispatches to appropriate services
2. **Application Layer**: Command Service, Router Service, Practice Service orchestrate business logic
3. **Domain Layer**: Entities (RawMessage, Document, Item, PracticeLog) and business rules
4. **Infrastructure Layer**: Database repositories, LLM clients, LINE SDK wrapper

Message flow:

1. LINE Webhook receives user message
2. Command Parser checks for hard-coded commands (deterministic first)
3. If no match, Router LLM classifies intent
4. Appropriate handler executes the action
5. Response sent back via LINE Reply API

---

## Technology Decisions

| Decision | Choice | Rationale | Alternatives Rejected |
|----------|--------|-----------|----------------------|
| Runtime | Python 3.11 | Best LLM SDK support, async/await, rapid development | Node.js (less mature LLM libraries), Go (slower iteration) |
| Web Framework | FastAPI | Async support, automatic OpenAPI docs, type hints | Flask (no native async), Django (too heavy for API-only) |
| Database | PostgreSQL via Supabase | JSONB support for flexible payload, managed service, built-in auth | SQLite (no concurrent writes), MongoDB (overkill for structured data) |
| ORM | SQLAlchemy 2.0 | Type-safe queries, async support, mature ecosystem | Raw SQL (maintenance burden), Prisma (Python support immature) |
| LLM Provider | Anthropic Claude Opus 4.5 (primary), OpenAI GPT-5.2 (fallback) | Superior Japanese teaching explanations, excellent instruction following for structured output, natural conversational tone | GPT-4o-mini (lower quality for teaching), Local LLM (latency/quality tradeoff) |
| LINE SDK | line-bot-sdk-python | Official SDK, well maintained | Raw HTTP (reinventing the wheel) |
| Deployment | Docker on Railway/Render | Simple deploy, auto-scaling, free tier available | AWS Lambda (cold start issues), VPS (more ops overhead) |

---

## Integration Points / APIs

- **LINE Messaging API**: Webhook endpoint receives events, Reply API sends responses. Requires channel access token and channel secret for signature verification.

- **Anthropic API** (Primary): Used for all LLM functions via Claude Opus 4.5:
  - Router: intent classification (structured output)
  - Extractor: vocab/grammar extraction (structured output)
  - Chat: learning explanations and user interaction
  - Practice Generator: cloze question generation (optional, can be template-based)

- **OpenAI API** (Fallback): GPT-5.2 activated when primary fails:
  - Trigger conditions: timeout > 15s, API error (5xx), or confidence < 0.5
  - Same prompt templates with JSON mode enabled

- **Supabase (PostgreSQL)**: Database connection via connection pooler. Uses SQLAlchemy async driver (asyncpg).

---

## Data Flow

### Ingest Flow (Save Command)

User message - LINE Webhook - Command Parser - Save Handler - raw_messages table - documents table (deferred) - Reply confirmation

### Analysis Flow (Analyze Command)

Analyze command - Document Service - fetch deferred doc - Extractor LLM - parse items - items table (upsert) - Reply summary

### Practice Flow

Practice command - Practice Service - select items (priority algorithm) - generate questions - Reply questions - User answers - Grader - practice_logs table - Reply feedback

---

## Project Structure

### Feature Documentation

| Path | Purpose |
|------|--------|
| `specs/001-line-jp-learning/spec.md` | Feature specification |
| `specs/001-line-jp-learning/plan.md` | This file |
| `specs/001-line-jp-learning/tasks.md` | Task decomposition |
| `specs/001-line-jp-learning/checklists/` | Quality checklists |

### Source Code

**Structure: Single project (web API)**

| Path | Purpose |
|------|--------|
| `src/main.py` | FastAPI app entry point |
| `src/api/` | API routes (webhook handler) |
| `src/services/` | Business logic services |
| `src/services/command_service.py` | Command parsing and dispatch |
| `src/services/router_service.py` | LLM intent classification |
| `src/services/extractor_service.py` | LLM content extraction |
| `src/services/practice_service.py` | Practice generation and grading |
| `src/repositories/` | Database access layer |
| `src/models/` | SQLAlchemy models |
| `src/models/raw_message.py` | RawMessage entity |
| `src/models/document.py` | Document entity |
| `src/models/item.py` | Item entity (vocab/grammar) |
| `src/models/practice_log.py` | PracticeLog entity |
| `src/schemas/` | Pydantic schemas for API/LLM |
| `src/lib/` | Utilities (text normalization, etc.) |
| `src/lib/normalizer.py` | Japanese text normalization |
| `src/lib/line_client.py` | LINE SDK wrapper |
| `src/lib/llm_client.py` | LLM client with Anthropic (primary) + OpenAI (fallback) |
| `src/config.py` | Configuration management |
| `tests/unit/` | Unit tests |
| `tests/integration/` | Integration tests |
| `tests/fixtures/` | Test data (Japanese samples) |

**Structure Decision**: Single project structure selected because this is a single API server with no separate frontend. All components run in one process.

---

## Data Model

### raw_messages

| Column | Type | Description |
|--------|------|-------------|
| raw_id | UUID (PK) | Primary key |
| user_id | TEXT (indexed) | Hashed LINE user ID |
| channel | TEXT | Fixed: "line" |
| raw_text | TEXT | Original message content |
| raw_meta | JSONB | LINE message metadata |
| created_at | TIMESTAMPTZ | Creation timestamp |
| is_deleted | BOOLEAN | Soft delete flag |

### documents

| Column | Type | Description |
|--------|------|-------------|
| doc_id | UUID (PK) | Primary key |
| raw_id | UUID (FK) | Reference to raw_messages |
| user_id | TEXT (indexed) | Hashed LINE user ID |
| lang | TEXT | ja / mixed / unknown |
| doc_type | TEXT | vocab / grammar / mixed / text |
| summary | TEXT | Optional summary |
| tags | JSONB | Array of tags |
| parse_status | TEXT | parsed / deferred / failed |
| parser_version | TEXT | e.g., "canon_v1" |
| llm_trace | JSONB | LLM call metadata |
| created_at | TIMESTAMPTZ | Creation timestamp |
| updated_at | TIMESTAMPTZ | Update timestamp |

### items

| Column | Type | Description |
|--------|------|-------------|
| item_id | UUID (PK) | Primary key |
| user_id | TEXT (indexed) | Hashed LINE user ID |
| doc_id | UUID (FK) | Reference to documents |
| item_type | TEXT | vocab / grammar |
| key | TEXT (indexed) | Unique key for deduplication |
| payload | JSONB | Type-specific fields |
| source_quote | TEXT | Original text snippet |
| confidence | FLOAT | 0-1 extraction confidence |
| created_at | TIMESTAMPTZ | Creation timestamp |
| is_deleted | BOOLEAN | Soft delete flag |

Unique constraint: `(user_id, item_type, key) WHERE is_deleted = false`

### practice_logs

| Column | Type | Description |
|--------|------|-------------|
| log_id | UUID (PK) | Primary key |
| user_id | TEXT (indexed) | Hashed LINE user ID |
| item_id | UUID (FK) | Reference to items |
| practice_type | TEXT | vocab_recall / grammar_cloze |
| prompt_snapshot | TEXT | Question text |
| user_answer | TEXT | User response |
| is_correct | BOOLEAN | Grading result |
| score | FLOAT | Optional score |
| feedback | TEXT | Optional feedback |
| created_at | TIMESTAMPTZ | Timestamp |

---

## LLM Prompts

### Router Prompt

System role: Japanese learning assistant router. Classify user intent into one of: save, practice, delete, search, chat, help, other. Output strict JSON.

Input: user_message, optional recent_messages

Output schema:
```
{
  "intent": "save | practice | delete | search | chat | help | other",
  "confidence": 0.0-1.0,
  "entities": {
    "keyword": "string | null",
    "delete_scope": "last | all | none",
    "practice_focus": "vocab | grammar | mixed | null"
  },
  "should_store_raw": true | false,
  "response_hint": "optional hint text"
}
```

### Extractor Prompt

System role: Japanese learning content structurer. Extract vocab and grammar items from text. Output strict JSON. Do not hallucinate - if unsure, add to warnings.

Input: raw_text, lang_hint=ja, extract_targets=["vocab", "grammar"], max_items=20

Output schema:
```
{
  "lang": "ja | mixed | unknown",
  "doc_type": "vocab | grammar | mixed | text",
  "tags": [],
  "items": [
    {
      "item_type": "vocab | grammar",
      "key": "vocab:surface or grammar:pattern",
      "source_quote": "original text",
      "confidence": 0.0-1.0,
      "payload": { type-specific fields }
    }
  ],
  "warnings": []
}
```

---

## Constitution Check

| Requirement | Status | Notes |
|-------------|--------|-------|
| Architecture follows established patterns | PASS | Layered architecture with clear separation |
| Technology decisions documented | PASS | All decisions with rationale |
| Integration points identified | PASS | LINE API, OpenAI API, Supabase |
| Constraints and risks documented | PASS | See below |
| No implementation details in spec | PASS | Spec is technology-agnostic |
| All FR mapped to components | PASS | See Project Structure |

---

## Constraints and Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM API latency spikes | High | Timeout handling (15s), auto-fallback to GPT-5.2, cache common patterns |
| LLM provider unavailability | High | Dual-provider architecture: Opus 4.5 primary, GPT-5.2 fallback on timeout/error/low-confidence |
| LLM extraction quality for edge cases | Medium | Confidence threshold (≥0.7 auto-accept, <0.5 triggers fallback), warnings in output, manual review option |
| LINE webhook timeout (30s) | Medium | Async processing for long operations, deferred analysis |
| OpenAI API rate limits | Low | Request queuing, exponential backoff |
| Japanese text normalization complexity | Medium | Use established library (jaconv), comprehensive test suite |
| Cost overrun from LLM calls | Medium | Token counting, usage alerts, template-based alternatives |

---

## Estimated Timeline

| Phase | Estimate | Notes |
|-------|----------|-------|
| Setup (project structure, DB, config) | 1 day | Includes Supabase setup, LINE bot creation |
| Core Models and Repositories | 1 day | SQLAlchemy models, CRUD operations |
| Command Service (hard-coded commands) | 1 day | Deterministic command parsing |
| Router Service (LLM integration) | 1 day | Intent classification |
| Extractor Service | 1.5 days | Vocab/grammar extraction, complex prompts |
| Practice Service | 1.5 days | Item selection, question generation, grading |
| LINE Integration | 0.5 day | Webhook handler, reply formatting |
| Testing | 2 days | Unit tests, integration tests, Japanese fixtures |
| Polish and Edge Cases | 1 day | Error handling, logging, monitoring |
| **Total** | **10.5 days** | Approximately 2 weeks |

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-01-27 | Initial plan based on spec v1.0.0 |
| 1.1.0 | 2026-01-27 | LLM provider changed to Claude Opus 4.5 (primary) with GPT-5.2 fallback |
