"""Command service for parsing and handling user commands.

T026: Implement command parser in src/services/command_service.py
T027: Implement save_raw handler in src/services/command_service.py
DoD: parse() 回傳正確的 CommandType；save_raw() 建立 raw_message + document
"""

import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.lib.security import hash_user_id
from src.repositories.document_repo import DocumentRepository
from src.repositories.raw_message_repo import RawMessageRepository
from src.schemas.command import CommandResult, CommandType, ParsedCommand
from src.templates.messages import Messages, format_save_success, truncate_content_preview

logger = logging.getLogger(__name__)


# Command patterns (case-insensitive)
COMMAND_PATTERNS: list[tuple[str, CommandType, bool]] = [
    # (pattern, command_type, requires_keyword)
    (r"^1$", CommandType.CONFIRM_SAVE, False),  # 確認入庫
    (r"^入庫$", CommandType.SAVE, False),
    (r"^分析$", CommandType.ANALYZE, False),
    (r"^練習$", CommandType.PRACTICE, False),
    (r"^查詢\s+(.+)$", CommandType.SEARCH, True),
    (r"^查詢$", CommandType.SEARCH, False),  # Missing keyword case
    (r"^刪除最後一筆$", CommandType.DELETE_LAST, False),
    (r"^清空資料$", CommandType.DELETE_ALL, False),
    (r"^確定清空資料$", CommandType.DELETE_CONFIRM, False),
    (r"^隱私$", CommandType.PRIVACY, False),
    (r"^(說明|幫助|help)$", CommandType.HELP, False),
    (r"^(用量|cost)$", CommandType.COST, False),
    (r"^(統計|進度)$", CommandType.STATS, False),
    (r"^切換(免費|便宜|嚴謹)$", CommandType.MODE_SWITCH, True),
    (r"^(免費模式|便宜模式|嚴謹模式)$", CommandType.MODE_SWITCH, True),
    (r"^(英文|日文)$", CommandType.SET_LANG, True),
    (r"^(結束練習|停止練習)$", CommandType.EXIT_PRACTICE, False),
]

# 語言名稱 → lang key 映射
LANG_NAME_MAP: dict[str, str] = {
    "英文": "en",
    "日文": "ja",
}

# 模式名稱 → mode key 映射
MODE_NAME_MAP: dict[str, str] = {
    "免費": "free",
    "便宜": "cheap",
    "嚴謹": "rigorous",
    "免費模式": "free",
    "便宜模式": "cheap",
    "嚴謹模式": "rigorous",
}


def parse_command(text: str) -> ParsedCommand:
    """Parse user message to identify command.

    Uses deterministic pattern matching for hard-coded commands.
    Unknown messages are marked as UNKNOWN for Router LLM handling.

    Args:
        text: User message text

    Returns:
        ParsedCommand with identified command type
    """
    if not text:
        return ParsedCommand(
            command_type=CommandType.UNKNOWN,
            raw_text="",
        )

    # Normalize: trim whitespace
    normalized = text.strip()

    # Try each pattern
    for pattern, command_type, has_keyword in COMMAND_PATTERNS:
        match = re.match(pattern, normalized, re.IGNORECASE)
        if match:
            keyword = match.group(1) if has_keyword and match.lastindex else None

            return ParsedCommand(
                command_type=command_type,
                raw_text=text,
                keyword=keyword,
                confidence=1.0,  # Hard-coded commands have 100% confidence
            )

    # No match - return UNKNOWN for Router LLM
    return ParsedCommand(
        command_type=CommandType.UNKNOWN,
        raw_text=text,
        confidence=0.0,
    )


class CommandService:
    """Service for executing user commands."""

    def __init__(self, session: AsyncSession):
        """Initialize command service.

        Args:
            session: Database session
        """
        self.session = session
        self.raw_message_repo = RawMessageRepository(session)
        self.document_repo = DocumentRepository(session)

    async def save_raw(
        self,
        line_user_id: str,
        content_text: str,
        raw_meta: dict[str, Any] | None = None,
    ) -> CommandResult:
        """Save raw message and create deferred document.

        T027: Implement save_raw handler
        DoD: save_raw(user_id, text) 建立 raw_message + document (deferred)；回傳 doc_id

        Args:
            line_user_id: Original LINE user ID (will be hashed)
            content_text: Content to save (previous message)
            raw_meta: Optional LINE message metadata

        Returns:
            CommandResult with doc_id on success
        """
        try:
            # Hash user ID for privacy
            user_id = hash_user_id(line_user_id)

            # Create raw message
            raw_message = await self.raw_message_repo.create_raw_message(
                user_id=user_id,
                raw_text=content_text,
                raw_meta=raw_meta,
            )

            # Create deferred document
            document = await self.document_repo.create_document(
                raw_id=raw_message.raw_id,
                user_id=user_id,
                parse_status="deferred",
            )

            logger.info(f"Saved raw message and document: {document.doc_id}")

            # 使用截斷內容作為預覽
            content_preview = truncate_content_preview(content_text)

            return CommandResult.ok(
                message=format_save_success(content_preview),
                doc_id=document.doc_id,
                raw_id=raw_message.raw_id,
            )

        except Exception as e:
            logger.exception(f"Failed to save raw: {e}")
            return CommandResult.fail(
                message=Messages.ERROR_SAVE,
                error=str(e),
            )

    async def get_previous_content(
        self,
        line_user_id: str,
    ) -> str | None:
        """Get previous message content for save command.

        Args:
            line_user_id: Original LINE user ID

        Returns:
            Previous message text if available, None otherwise
        """
        user_id = hash_user_id(line_user_id)

        messages = await self.raw_message_repo.get_latest_by_user(
            user_id=user_id,
            limit=1,
        )

        if messages:
            return messages[0].raw_text

        return None


# ============================================================================
# 向後相容的 helper 函數 (re-export from Messages)
# 建議新程式碼直接使用 src.templates.messages.Messages
# ============================================================================


def get_help_message() -> str:
    """Get help message with available commands.
    
    Deprecated: 建議使用 Messages.HELP
    """
    return Messages.HELP


def get_privacy_message() -> str:
    """Get privacy policy message.
    
    Deprecated: 建議使用 Messages.PRIVACY
    """
    return Messages.PRIVACY


def get_no_content_message() -> str:
    """Get message when no content to save.
    
    Deprecated: 建議使用 Messages.SAVE_NO_CONTENT
    """
    return Messages.SAVE_NO_CONTENT


def get_search_hint_message() -> str:
    """Get message when search keyword is missing.
    
    Deprecated: 建議使用 Messages.SEARCH_HINT
    """
    return Messages.SEARCH_HINT
