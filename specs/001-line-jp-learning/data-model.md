# Data Model: LINE 日語學習助教 Bot

**Feature ID**: `001-line-jp-learning`  
**Version**: 1.0.0  
**Date**: 2026-01-27

---

## Entity Relationship Overview

```
User (LINE)
    |
    +-- raw_messages (1:N)
    |       |
    |       +-- documents (1:1)
    |               |
    |               +-- items (1:N)
    |
    +-- practice_logs (1:N)
            |
            +-- items (N:1)
```

---

## Entities

### 1. RawMessage

Immutable record of user input. Never modified after creation.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| raw_id | UUID | PK | Unique identifier |
| user_id | TEXT | NOT NULL, INDEXED | Hashed LINE user ID |
| channel | TEXT | NOT NULL, DEFAULT "line" | Source channel |
| raw_text | TEXT | NOT NULL | Original message content |
| raw_meta | JSONB | NULLABLE | LINE message metadata (message_id, timestamp, user_note) |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Creation timestamp |
| is_deleted | BOOLEAN | NOT NULL, DEFAULT FALSE | Soft delete flag |

**Indexes:**
- `idx_raw_messages_user_created` on (user_id, created_at DESC)
- `idx_raw_messages_meta` GIN on (raw_meta) [optional]

---

### 2. Document

Represents a parsed or pending document derived from a raw message.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| doc_id | UUID | PK | Unique identifier |
| raw_id | UUID | FK to raw_messages, NOT NULL | Source raw message |
| user_id | TEXT | NOT NULL, INDEXED | Hashed LINE user ID |
| lang | TEXT | NOT NULL | Language: "ja", "mixed", "unknown" |
| doc_type | TEXT | NOT NULL | Type: "vocab", "grammar", "mixed", "text" |
| summary | TEXT | NULLABLE | Optional summary |
| tags | JSONB | NOT NULL, DEFAULT [] | Array of string tags |
| parse_status | TEXT | NOT NULL | Status: "parsed", "deferred", "failed" |
| parser_version | TEXT | NULLABLE | e.g., "canon_v1" |
| llm_trace | JSONB | NULLABLE | LLM call metadata (model, prompt, tokens, cost) |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Last update timestamp |

**Indexes:**
- `idx_documents_user_created` on (user_id, created_at DESC)
- `idx_documents_tags` GIN on (tags) [optional]

**Business Rules:**
- One document per raw_message
- parse_status transitions: deferred to parsed, deferred to failed, failed to parsed (retry)

---

### 3. Item

Learning unit extracted from a document. Can be vocab or grammar type.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| item_id | UUID | PK | Unique identifier |
| user_id | TEXT | NOT NULL, INDEXED | Hashed LINE user ID |
| doc_id | UUID | FK to documents, NOT NULL | Source document |
| item_type | TEXT | NOT NULL | Type: "vocab", "grammar" |
| key | TEXT | NOT NULL, INDEXED | Deduplication key |
| payload | JSONB | NOT NULL | Type-specific data |
| source_quote | TEXT | NULLABLE | Original text snippet |
| confidence | FLOAT | NOT NULL, CHECK 0 to 1 | Extraction confidence |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Creation timestamp |
| is_deleted | BOOLEAN | NOT NULL, DEFAULT FALSE | Soft delete flag |

**Indexes:**
- `idx_items_user_type_key` UNIQUE on (user_id, item_type, key) WHERE is_deleted = FALSE
- `idx_items_payload` GIN on (payload) [optional]

**Key Generation Rules:**
- Vocab: `vocab:<normalized_surface>`
- Grammar: `grammar:<normalized_pattern>`

---

### 4. PracticeLog

Record of a single practice attempt.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| log_id | UUID | PK | Unique identifier |
| user_id | TEXT | NOT NULL, INDEXED | Hashed LINE user ID |
| item_id | UUID | FK to items, NOT NULL | Practiced item |
| practice_type | TEXT | NOT NULL | Type: "vocab_recall", "grammar_cloze" |
| prompt_snapshot | TEXT | NULLABLE | Question text |
| user_answer | TEXT | NOT NULL | User response |
| is_correct | BOOLEAN | NOT NULL | Grading result |
| score | FLOAT | NULLABLE | Optional numeric score |
| feedback | TEXT | NULLABLE | Optional feedback text |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Timestamp |

**Indexes:**
- `idx_practice_logs_user_created` on (user_id, created_at DESC)
- `idx_practice_logs_user_item_created` on (user_id, item_id, created_at DESC)

---

## Payload Schemas

### Vocab Payload

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

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| surface | string | YES | Dictionary form |
| reading | string | YES | Hiragana reading |
| pos | string | NO | Part of speech |
| glossary_zh | string[] | YES | Chinese meanings |
| example_ja | string | NO | Example sentence (Japanese) |
| example_zh | string | NO | Example sentence (Chinese) |
| level | string | NO | JLPT level (N5-N1) |
| notes | string | NO | Additional notes |

---

### Grammar Payload

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

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| pattern | string | YES | Grammar pattern |
| meaning_zh | string | YES | Chinese meaning |
| usage | string[] | NO | Usage notes |
| form_notes | string | NO | Formation rules |
| example_ja | string | NO | Example sentence (Japanese) |
| example_zh | string | NO | Example sentence (Chinese) |
| level | string | NO | JLPT level (N5-N1) |
| common_mistakes | string[] | NO | Common errors |

---

## State Transitions

### Document parse_status

```
[Created] --> deferred --> parsed
                |
                +--> failed --> parsed (retry)
```

### Item is_deleted

```
[Created] --> is_deleted=false --> is_deleted=true (soft delete)
```

Items with is_deleted=true are excluded from:
- Practice selection
- Search results
- Unique constraint check

---

## Validation Rules

### RawMessage
- raw_text must not be empty
- user_id must be a valid hash (64 hex characters for SHA-256)

### Document
- lang must be one of: "ja", "mixed", "unknown"
- doc_type must be one of: "vocab", "grammar", "mixed", "text"
- parse_status must be one of: "parsed", "deferred", "failed"

### Item
- item_type must be one of: "vocab", "grammar"
- key must follow pattern: `<item_type>:<identifier>`
- confidence must be between 0.0 and 1.0
- payload must validate against corresponding schema

### PracticeLog
- practice_type must be one of: "vocab_recall", "grammar_cloze"
- user_answer must not be empty

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-01-27 | Initial data model |
