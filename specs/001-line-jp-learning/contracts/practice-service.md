# API Contract: Practice Service

**Service**: Practice Generator  
**Version**: 1.0.0  
**Date**: 2026-01-27

---

## Purpose

Generate practice questions from user's items and grade answers.

---

## Endpoints

### 1. Generate Practice

Generate a set of practice questions.

#### Request

```json
{
  "user_id": "string (required)",
  "count": 5,
  "focus": "vocab | grammar | mixed | null"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| user_id | string | YES | - | Hashed user ID |
| count | integer | NO | 5 | Number of questions |
| focus | string | NO | null | Filter by item type |

#### Response

```json
{
  "practice_type": "vocab_recall | grammar_cloze",
  "questions": [
    {
      "item_id": "uuid",
      "question": "『思考』的日文是？",
      "expected": ["考える"],
      "hint": "かんがえる",
      "explain": "可用於『我再想想看』"
    }
  ],
  "metadata": {
    "total_items": 42,
    "items_used": 5
  }
}
```

---

### 2. Grade Answer

Grade a single answer.

#### Request

```json
{
  "user_id": "string (required)",
  "item_id": "uuid (required)",
  "practice_type": "vocab_recall | grammar_cloze",
  "user_answer": "string (required)"
}
```

#### Response

```json
{
  "is_correct": true,
  "expected": ["考える"],
  "feedback": "正確！",
  "hint": "かんがえる"
}
```

---

## Question Types

### Vocab Recall

Generate question from vocab item payload.

**Question Template:**
- Chinese to Japanese: "『{glossary_zh[0]}』的日文是？"
- Japanese to Chinese: "『{surface}』的中文是？"

**Expected Answers:**
- Chinese to Japanese: [surface, reading] (both accepted)
- Japanese to Chinese: glossary_zh array

**Example:**

```json
{
  "item_id": "abc-123",
  "question": "『思考』的日文是？",
  "expected": ["考える", "かんがえる"],
  "hint": "動詞",
  "explain": "可用於委婉回覆"
}
```

---

### Grammar Cloze

Generate cloze question from grammar item.

**Question Template:**
- "填入適當的文法：{example_ja with blank}"
- Blank replaces the pattern in example

**Expected Answers:**
- Pattern or variations

**Example:**

```json
{
  "item_id": "def-456",
  "question": "填入適當的文法：財布を忘れて＿＿。",
  "expected": ["しまった", "しまう"],
  "hint": "表示遺憾",
  "explain": "〜てしまう：表示不小心做了某事"
}
```

---

## Item Selection Algorithm

Priority order (highest to lowest):

1. **Recent items** (created within 24 hours)
   - New items need reinforcement
   - SELECT WHERE created_at > NOW() - INTERVAL '24 hours'

2. **Error-prone items** (high error rate in last 7 days)
   - Items user struggles with
   - SELECT WHERE error_rate > 0.5 in recent logs

3. **Stale items** (longest time since last practice)
   - Items not reviewed recently
   - SELECT ORDER BY last_practiced_at ASC NULLS FIRST

4. **Random** (fallback)
   - Ensure variety
   - SELECT ORDER BY RANDOM()

**Selection Query Pseudocode:**

```sql
WITH item_stats AS (
  SELECT 
    i.item_id,
    i.created_at,
    COUNT(CASE WHEN pl.is_correct = false THEN 1 END)::float / 
      NULLIF(COUNT(pl.log_id), 0) as error_rate,
    MAX(pl.created_at) as last_practiced_at
  FROM items i
  LEFT JOIN practice_logs pl ON i.item_id = pl.item_id
  WHERE i.user_id = :user_id 
    AND i.is_deleted = false
  GROUP BY i.item_id
)
SELECT item_id FROM item_stats
ORDER BY
  CASE WHEN created_at > NOW() - INTERVAL '24 hours' THEN 0 ELSE 1 END,
  CASE WHEN error_rate > 0.5 THEN 0 ELSE 1 END,
  last_practiced_at ASC NULLS FIRST,
  RANDOM()
LIMIT :count
```

---

## Answer Normalization

Before comparing user_answer to expected:

1. **Whitespace**: Trim and collapse multiple spaces
2. **Width**: Convert full-width to half-width (or vice versa)
3. **Kana**: Accept hiragana/katakana interchangeably
4. **Kanji/Kana**: For vocab, accept both kanji and reading

**Normalization Steps:**

```python
def normalize(text: str) -> str:
    text = text.strip()
    text = jaconv.z2h(text, kana=False, digit=True, ascii=True)
    text = jaconv.kata2hira(text)
    return text.lower()

def is_correct(user_answer: str, expected: list[str]) -> bool:
    normalized_answer = normalize(user_answer)
    return any(
        normalize(exp) == normalized_answer 
        for exp in expected
    )
```

---

## Business Rules

1. **Minimum items**: If user has < 5 items, return error with count
2. **No duplicates**: Same item should not appear twice in one practice set
3. **Type balance**: If focus=mixed, try to include both vocab and grammar
4. **Logging**: Every graded answer must be logged to practice_logs

---

## Error Responses

| Scenario | Response |
|----------|----------|
| Insufficient items | `{"error": "insufficient_items", "count": 3, "required": 5}` |
| Item not found | `{"error": "item_not_found", "item_id": "..."}` |
| Invalid practice type | `{"error": "invalid_practice_type"}` |

---

## Example Flow

### Generate

**Request:**
```json
{
  "user_id": "abc123hash",
  "count": 5,
  "focus": "vocab"
}
```

**Response:**
```json
{
  "practice_type": "vocab_recall",
  "questions": [
    {
      "item_id": "item-001",
      "question": "『思考』的日文是？",
      "expected": ["考える", "かんがえる"],
      "hint": "動詞，5個字",
      "explain": "常用於委婉表達"
    },
    {
      "item_id": "item-002",
      "question": "『錢包』的日文是？",
      "expected": ["財布", "さいふ"],
      "hint": "名詞，2個字",
      "explain": ""
    }
  ],
  "metadata": {
    "total_items": 42,
    "items_used": 2
  }
}
```

### Grade

**Request:**
```json
{
  "user_id": "abc123hash",
  "item_id": "item-001",
  "practice_type": "vocab_recall",
  "user_answer": "かんがえる"
}
```

**Response:**
```json
{
  "is_correct": true,
  "expected": ["考える", "かんがえる"],
  "feedback": "正確！漢字寫法是「考える」",
  "hint": null
}
```
