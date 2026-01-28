# API Contract: Extractor Service

**Service**: Extractor LLM  
**Version**: 1.0.0  
**Date**: 2026-01-27

---

## Purpose

Extract vocabulary and grammar items from Japanese text for practice generation.

---

## Request

### Input Schema

```json
{
  "raw_text": "string (required)",
  "lang_hint": "ja",
  "extract_targets": ["vocab", "grammar"],
  "max_items_per_doc": 20
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| raw_text | string | YES | - | Text to extract from |
| lang_hint | string | NO | "ja" | Expected language |
| extract_targets | string[] | NO | ["vocab", "grammar"] | What to extract |
| max_items_per_doc | integer | NO | 20 | Maximum items to return |

---

## Response

### Output Schema

```json
{
  "lang": "ja | mixed | unknown",
  "doc_type": "vocab | grammar | mixed | text",
  "tags": ["string"],
  "items": [
    {
      "item_type": "vocab | grammar",
      "key": "vocab:考える",
      "source_quote": "考える",
      "confidence": 0.92,
      "payload": {}
    }
  ],
  "warnings": ["string"]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| lang | string | YES | Detected language |
| doc_type | string | YES | Content type classification |
| tags | string[] | YES | Auto-generated tags |
| items | array | YES | Extracted items |
| warnings | string[] | YES | Extraction warnings |

---

## Item Payloads

### Vocab Item

```json
{
  "item_type": "vocab",
  "key": "vocab:考える",
  "source_quote": "もう少し考えてみます",
  "confidence": 0.92,
  "payload": {
    "surface": "考える",
    "reading": "かんがえる",
    "pos": "verb",
    "glossary_zh": ["思考", "考慮"],
    "example_ja": "もう少し考えてみます。",
    "example_zh": "我再想想看。",
    "level": "N3",
    "notes": ""
  }
}
```

### Grammar Item

```json
{
  "item_type": "grammar",
  "key": "grammar:〜てしまう",
  "source_quote": "忘れてしまった",
  "confidence": 0.88,
  "payload": {
    "pattern": "〜てしまう",
    "meaning_zh": "表示遺憾/不小心做了…",
    "usage": ["常見語感是『不小心』或『遺憾』"],
    "form_notes": "Vて + しまう",
    "example_ja": "財布を忘れてしまった。",
    "example_zh": "我不小心忘了帶錢包。",
    "level": "N3",
    "common_mistakes": []
  }
}
```

---

## Business Rules

1. Key normalization:
   - Vocab: lowercase, remove whitespace, use dictionary form
   - Grammar: normalize pattern notation (〜 vs ~)

2. Confidence thresholds:
   - confidence >= 0.7: auto-accept
   - confidence < 0.7: add to warnings

3. Deduplication:
   - If item with same key exists for user, update payload instead of create

4. Language detection:
   - Pure Japanese: "ja"
   - Japanese + other: "mixed"
   - No Japanese detected: "unknown"

---

## Warning Types

| Warning | Meaning |
|---------|---------|
| "content_too_short" | Input less than 5 characters |
| "no_japanese_detected" | No Japanese text found |
| "low_confidence_items" | Some items below threshold |
| "max_items_reached" | Truncated to max_items_per_doc |
| "extraction_partial" | Some content could not be parsed |

---

## Error Handling

| Scenario | Response |
|----------|----------|
| LLM timeout | Return empty items, warning "extraction_failed" |
| Invalid JSON | Retry once, then return empty items |
| No extractable content | Return empty items, warning "no_japanese_detected" |

---

## Example

### Request

```json
{
  "raw_text": "今日は財布を忘れてしまった。考えてみたけど、どこに置いたか分からない。",
  "lang_hint": "ja",
  "extract_targets": ["vocab", "grammar"],
  "max_items_per_doc": 20
}
```

### Response

```json
{
  "lang": "ja",
  "doc_type": "mixed",
  "tags": ["daily", "N3"],
  "items": [
    {
      "item_type": "vocab",
      "key": "vocab:財布",
      "source_quote": "財布を忘れて",
      "confidence": 0.95,
      "payload": {
        "surface": "財布",
        "reading": "さいふ",
        "pos": "noun",
        "glossary_zh": ["錢包"],
        "example_ja": "財布を忘れてしまった。",
        "example_zh": "我不小心忘了帶錢包。",
        "level": "N4",
        "notes": ""
      }
    },
    {
      "item_type": "grammar",
      "key": "grammar:〜てしまう",
      "source_quote": "忘れてしまった",
      "confidence": 0.90,
      "payload": {
        "pattern": "〜てしまう",
        "meaning_zh": "表示遺憾或不小心做了某事",
        "usage": ["表示遺憾", "口語常縮約為〜ちゃう"],
        "form_notes": "Vて + しまう",
        "example_ja": "財布を忘れてしまった。",
        "example_zh": "我不小心忘了帶錢包。",
        "level": "N3",
        "common_mistakes": []
      }
    },
    {
      "item_type": "grammar",
      "key": "grammar:〜てみる",
      "source_quote": "考えてみた",
      "confidence": 0.88,
      "payload": {
        "pattern": "〜てみる",
        "meaning_zh": "試著做某事",
        "usage": ["表示嘗試"],
        "form_notes": "Vて + みる",
        "example_ja": "考えてみたけど分からない。",
        "example_zh": "我試著想了但不知道。",
        "level": "N4",
        "common_mistakes": []
      }
    }
  ],
  "warnings": []
}
```
