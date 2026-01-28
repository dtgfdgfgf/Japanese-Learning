# API Contract: Router Service

**Service**: Router LLM  
**Version**: 1.0.0  
**Date**: 2026-01-27

---

## Purpose

Classify user intent from LINE message to route to appropriate handler.

---

## Request

### Input Schema

```json
{
  "user_message": "string (required)",
  "recent_messages": [
    {
      "role": "user | assistant",
      "content": "string"
    }
  ],
  "user_context": {
    "last_doc_id": "uuid | null",
    "last_practice_type": "vocab_recall | grammar_cloze | null"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| user_message | string | YES | Current user message |
| recent_messages | array | NO | Last N conversation turns (default: 6) |
| user_context | object | NO | Optional context for better routing |

---

## Response

### Output Schema

```json
{
  "intent": "save | practice | delete | search | chat | help | other",
  "confidence": 0.85,
  "entities": {
    "keyword": "string | null",
    "delete_scope": "last | all | none",
    "practice_focus": "vocab | grammar | mixed | null"
  },
  "should_store_raw": true,
  "response_hint": "optional hint text"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| intent | string | YES | Classified intent |
| confidence | float | YES | 0.0 to 1.0 confidence score |
| entities.keyword | string | NO | Extracted search keyword |
| entities.delete_scope | string | NO | Delete target scope |
| entities.practice_focus | string | NO | Practice type preference |
| should_store_raw | boolean | YES | Whether to save raw message |
| response_hint | string | NO | Suggested response text |

---

## Intent Values

| Intent | Trigger Examples | Action |
|--------|------------------|--------|
| save | "這個單字很重要", "記一下這個" | Auto-save with deferred parse |
| practice | "來練習", "出題", "考考我" | Generate practice questions |
| delete | "刪掉", "不要了" | Delete flow (with scope check) |
| search | "找一下...", "有沒有..." | Search items |
| chat | "這個文法怎麼用?", "幫我解釋" | Learning assistant chat |
| help | "怎麼用", "指令" | Show help message |
| other | Unclassified | Default to help |

---

## Business Rules

1. If confidence >= 0.80 and intent = "save": auto-save raw, respond with analysis prompt
2. If confidence < 0.80 and intent = "save": ask user to confirm
3. If intent = "delete" and delete_scope = "all": require confirmation
4. If intent = "search" and keyword is null: prompt for keyword

---

## Error Handling

| Scenario | Response |
|----------|----------|
| LLM timeout | Return intent="other", confidence=0.0, response_hint="請稍後再試" |
| Invalid JSON from LLM | Retry once, then return intent="other" |
| Rate limit | Queue request, retry with backoff |

---

## Example

### Request

```json
{
  "user_message": "考える這個單字要記起來",
  "recent_messages": [],
  "user_context": null
}
```

### Response

```json
{
  "intent": "save",
  "confidence": 0.92,
  "entities": {
    "keyword": null,
    "delete_scope": "none",
    "practice_focus": null
  },
  "should_store_raw": true,
  "response_hint": "已幫你存起來"
}
```
