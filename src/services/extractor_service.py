"""
Extractor service for analyzing Japanese text and extracting vocab/grammar items.

T037: Implement ExtractorService
DoD: extract(doc_id) 回傳 ExtractorResponse；長文 (>2000 字) 限制 max_items=20
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.lib.llm_client import LLMClient, LLMTrace
from src.lib.normalizer import detect_language
from src.prompts.extractor import format_extractor_request, get_system_prompt
from src.repositories.api_usage_log_repo import ApiUsageLogRepository
from src.repositories.document_repo import DocumentRepository
from src.repositories.item_repo import ItemRepository
from src.repositories.raw_message_repo import RawMessageRepository
from src.schemas.extractor import (
    ExtractedItem,
    ExtractionSummary,
    ExtractorResponse,
)

logger = logging.getLogger(__name__)

# Constants
LONG_TEXT_THRESHOLD = 2000  # characters
DEFAULT_MAX_ITEMS = 20
SHORT_TEXT_MAX_ITEMS = 10


class ExtractorService:
    """Service for extracting vocabulary and grammar from Japanese text."""

    def __init__(
        self,
        session: AsyncSession,
        llm_client: LLMClient | None = None,
    ):
        """
        Initialize ExtractorService.
        
        Args:
            session: Database session
            llm_client: Optional LLM client (creates new one if not provided)
        """
        self.session = session
        self.llm_client = llm_client or LLMClient()
        self.raw_message_repo = RawMessageRepository(session)
        self.document_repo = DocumentRepository(session)
        self.item_repo = ItemRepository(session)
        self.usage_repo = ApiUsageLogRepository(session)

    async def extract(
        self,
        doc_id: str,
        user_id: str,
    ) -> ExtractorResponse:
        """
        Extract vocabulary and grammar items from a document.
        
        Args:
            doc_id: Document ID to process
            user_id: User ID (hashed) for item ownership
            
        Returns:
            ExtractorResponse with extracted items
            
        Raises:
            ValueError: If document not found or already processed
        """
        # Get document
        document = await self.document_repo.get_by_id(doc_id)
        if not document:
            raise ValueError(f"Document not found: {doc_id}")

        if document.parse_status == "parsed":
            logger.warning(f"Document {doc_id} already parsed")
            return ExtractorResponse(
                doc_id=doc_id,
                items=[],
                warnings=["Document already parsed"],
            )

        # Get raw message text
        raw_message = await self.raw_message_repo.get_by_id(document.raw_id)
        if not raw_message:
            raise ValueError(f"Raw message not found for document: {doc_id}")

        raw_text = raw_message.raw_text

        # Detect language
        lang = detect_language(raw_text)
        if lang not in ("ja", "unknown"):
            logger.warning(f"Document {doc_id} doesn't appear to be Japanese: {lang}")
            await self._update_document_status(doc_id, "skipped", lang)
            return ExtractorResponse(
                doc_id=doc_id,
                items=[],
                warnings=[f"Text doesn't appear to be Japanese (detected: {lang})"],
            )

        # Determine max items based on text length
        text_length = len(raw_text)
        max_items = DEFAULT_MAX_ITEMS if text_length > LONG_TEXT_THRESHOLD else SHORT_TEXT_MAX_ITEMS

        # Call LLM for extraction
        try:
            items, llm_trace = await self._call_llm_extraction(raw_text, max_items)
            # 記錄 API 用量
            if llm_trace:
                await self.usage_repo.create_log(
                    user_id=user_id,
                    trace=llm_trace,
                    operation="extraction",
                )
        except Exception as e:
            logger.error(f"LLM extraction failed for {doc_id}: {e}")
            await self._update_document_status(doc_id, "failed", lang)
            return ExtractorResponse(
                doc_id=doc_id,
                items=[],
                warnings=[f"Extraction failed: {str(e)}"],
            )

        # Save items to database
        saved_items = []
        for item in items:
            try:
                saved_item = await self.item_repo.upsert(
                    user_id=user_id,
                    doc_id=doc_id,
                    item_type=item.item_type,
                    key=item.key,
                    payload=item.to_payload(),
                    source_quote=item.source_quote,
                    confidence=item.confidence,
                )
                saved_items.append(item)
                logger.debug(f"Saved item: {item.key}")
            except Exception as e:
                logger.error(f"Failed to save item {item.key}: {e}")

        # Update document status
        await self._update_document_status(doc_id, "parsed", lang)

        # Build response
        response = ExtractorResponse.from_items(doc_id, saved_items)

        if len(saved_items) < len(items):
            response.warnings.append(
                f"Some items failed to save ({len(items) - len(saved_items)} failures)"
            )

        if text_length > LONG_TEXT_THRESHOLD:
            response.warnings.append("Long text - extraction limited to 20 items")

        return response

    async def _call_llm_extraction(
        self,
        raw_text: str,
        max_items: int,
    ) -> tuple[list[ExtractedItem], LLMTrace]:
        """
        Call LLM to extract items from text.
        
        Args:
            raw_text: Text to analyze
            max_items: Maximum items to extract
            
        Returns:
            Tuple of (list of ExtractedItem objects, LLMTrace)
        """
        system_prompt = get_system_prompt(max_items)
        user_message = format_extractor_request(raw_text, max_items)

        # Call LLM with JSON mode
        # complete_json 返回 (parsed_dict, LLMTrace)
        response_data, llm_trace = await self.llm_client.complete_json(
            system_prompt=system_prompt,
            user_message=user_message,
        )

        # 記錄 LLM trace 供 debug 用
        logger.debug(f"LLM extraction trace: {llm_trace.to_dict()}")

        # Parse response
        items = []
        raw_items = response_data.get("items", [])

        for raw_item in raw_items[:max_items]:
            try:
                item = ExtractedItem(**raw_item)
                items.append(item)
            except Exception as e:
                logger.warning(f"Failed to parse item: {e}, data: {raw_item}")

        return items, llm_trace

    async def _update_document_status(
        self,
        doc_id: str,
        status: str,
        lang: str,
    ) -> None:
        """更新文件解析狀態。
        
        Args:
            doc_id: Document ID
            status: New parse status
            lang: Detected language
        """
        await self.document_repo.update(
            doc_id,
            parse_status=status,
            lang=lang,
            parser_version="v1.0.0",
        )

    async def get_deferred_documents(
        self,
        user_id: str,
        limit: int = 10,
    ) -> list:
        """
        Get documents pending analysis for a user.
        
        Args:
            user_id: User ID (hashed)
            limit: Maximum documents to return
            
        Returns:
            List of documents with parse_status='deferred'
        """
        return await self.document_repo.get_deferred_by_user(user_id, limit)


def create_extraction_summary(response: ExtractorResponse) -> ExtractionSummary:
    """
    Create summary from extraction response.
    
    Args:
        response: ExtractorResponse from extraction
        
    Returns:
        ExtractionSummary for LINE reply
    """
    return ExtractionSummary(
        vocab_count=response.vocab_count,
        grammar_count=response.grammar_count,
        total_count=response.vocab_count + response.grammar_count,
        is_truncated="limited" in " ".join(response.warnings).lower(),
    )
