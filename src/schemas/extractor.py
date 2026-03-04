"""
Pydantic schemas for Extractor service.

T035: Create Pydantic schemas for Extractor
DoD: ExtractorRequest, ExtractorResponse, ExtractedItem schemas 符合 plan.md Extractor Output
"""

from pydantic import BaseModel, Field


class ExtractedItem(BaseModel):
    """Represents a single extracted vocabulary or grammar item."""
    
    item_type: str = Field(
        ...,
        description="Type of item: 'vocab' or 'grammar'",
        pattern="^(vocab|grammar)$"
    )
    key: str = Field(
        ...,
        description="Unique key for the item, e.g., 'vocab:考える' or 'grammar:〜てしまう'"
    )
    surface: str | None = Field(
        None,
        description="Surface form for vocab items (e.g., '考える')"
    )
    reading: str | None = Field(
        None,
        description="Reading in hiragana (e.g., 'かんがえる') — 日文用"
    )
    pronunciation: str | None = Field(
        None,
        description="IPA pronunciation (e.g., '/kənˈsɪdər/') — 英文用"
    )
    pos: str | None = Field(
        None,
        description="Part of speech (e.g., 'verb', 'noun', 'i-adjective')"
    )
    glossary_zh: list[str] | None = Field(
        None,
        description="Chinese glossary translations"
    )
    pattern: str | None = Field(
        None,
        description="Grammar pattern (e.g., '〜てしまう')"
    )
    meaning_zh: str | None = Field(
        None,
        description="Chinese meaning for grammar items"
    )
    form_notes: str | None = Field(
        None,
        description="Formation notes (e.g., 'Vて + しまう')"
    )
    example: str | None = Field(
        None,
        description="Example sentence"
    )
    example_translation: str | None = Field(
        None,
        description="Example sentence translation"
    )
    source_quote: str | None = Field(
        None,
        description="Original text quote this item was extracted from"
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Extraction confidence score"
    )
    display: str | None = Field(
        None,
        description="LLM 生成的完整分析文字，用於 LINE 顯示"
    )

    def to_payload(self) -> dict:
        """Convert to payload dict for Item model."""
        if self.item_type == "vocab":
            payload: dict = {
                "surface": self.surface,
                "pos": self.pos,
                "glossary_zh": self.glossary_zh or [],
                "example": self.example,
                "example_translation": self.example_translation,
            }
            # 日文用 reading，英文用 pronunciation
            if self.reading:
                payload["reading"] = self.reading
            if self.pronunciation:
                payload["pronunciation"] = self.pronunciation
            if self.display:
                payload["display"] = self.display
            return payload
        else:  # grammar
            payload = {
                "pattern": self.pattern,
                "meaning_zh": self.meaning_zh,
                "form_notes": self.form_notes,
                "example": self.example,
                "example_translation": self.example_translation,
            }
            if self.display:
                payload["display"] = self.display
            return payload


class ExtractorRequest(BaseModel):
    """Request payload for Extractor service."""
    
    doc_id: str = Field(..., description="Document ID to extract from")
    raw_text: str = Field(..., description="Raw text content to analyze")
    max_items: int = Field(
        default=20,
        ge=1,
        le=50,
        description="Maximum number of items to extract"
    )
    lang_hint: str | None = Field(
        default=None,
        description="Language hint (e.g., 'ja')"
    )


class ExtractorResponse(BaseModel):
    """Response from Extractor service."""
    
    doc_id: str = Field(..., description="Document ID that was processed")
    items: list[ExtractedItem] = Field(
        default_factory=list,
        description="List of extracted items"
    )
    vocab_count: int = Field(default=0, description="Number of vocabulary items")
    grammar_count: int = Field(default=0, description="Number of grammar items")
    warnings: list[str] = Field(
        default_factory=list,
        description="Any warnings during extraction"
    )
    
    @classmethod
    def from_items(cls, doc_id: str, items: list[ExtractedItem]) -> "ExtractorResponse":
        """Create response from list of items."""
        vocab_count = sum(1 for item in items if item.item_type == "vocab")
        grammar_count = sum(1 for item in items if item.item_type == "grammar")
        return cls(
            doc_id=doc_id,
            items=items,
            vocab_count=vocab_count,
            grammar_count=grammar_count,
        )


class ExtractionSummary(BaseModel):
    """Summary of extraction for LINE reply."""
    
    vocab_count: int = Field(default=0, description="Number of vocabulary items")
    grammar_count: int = Field(default=0, description="Number of grammar items")
    total_count: int = Field(default=0, description="Total items extracted")
    is_truncated: bool = Field(
        default=False,
        description="Whether the extraction was truncated due to max_items"
    )
    
    def to_message(self) -> str:
        """Format as LINE reply message."""
        if self.total_count == 0:
            return "沒有發現可學習的單字或文法 📝"

        parts = []
        if self.vocab_count > 0:
            parts.append(f"{self.vocab_count} 個單字")
        if self.grammar_count > 0:
            parts.append(f"{self.grammar_count} 個文法")

        message = f"✨ 抽出 {' 和 '.join(parts)}"

        if self.is_truncated:
            message += "\n（內容較長，已限制抽取數量）"

        return message
