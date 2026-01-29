"""LINE Messaging API client wrapper.

T022: Create LINE client wrapper in src/lib/line_client.py
DoD: reply_message(reply_token, text) 可送出回覆；signature 驗證方法可用
"""

import hashlib
import hmac
import logging
from base64 import b64encode
from typing import Any

from linebot.v3 import WebhookParser
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PostbackAction,
    QuickReply,
    QuickReplyItem,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, PostbackEvent, TextMessageContent

from src.config import settings

logger = logging.getLogger(__name__)


class LineClient:
    """LINE Messaging API client wrapper.

    Provides simplified interface for:
    - Sending reply messages
    - Validating webhook signatures
    - Parsing webhook events
    """

    def __init__(
        self,
        channel_access_token: str | None = None,
        channel_secret: str | None = None,
    ):
        """Initialize LINE client.

        Args:
            channel_access_token: LINE channel access token (defaults to settings)
            channel_secret: LINE channel secret (defaults to settings)
        """
        self.channel_access_token = (
            channel_access_token or settings.line_channel_access_token
        )
        self.channel_secret = channel_secret or settings.line_channel_secret

        # Setup LINE SDK
        self.configuration = Configuration(
            access_token=self.channel_access_token,
        )
        self.parser = WebhookParser(self.channel_secret)

    def verify_signature(self, body: str, signature: str) -> bool:
        """Verify LINE webhook signature.

        Args:
            body: Request body as string
            signature: X-Line-Signature header value

        Returns:
            True if signature is valid, False otherwise
        """
        if not signature:
            return False

        # Calculate expected signature
        hash_value = hmac.new(
            self.channel_secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        expected_signature = b64encode(hash_value).decode("utf-8")

        # Constant-time comparison to prevent timing attacks
        return hmac.compare_digest(signature, expected_signature)

    async def reply_message(
        self,
        reply_token: str,
        text: str,
    ) -> bool:
        """Send a text reply message.

        Args:
            reply_token: Reply token from webhook event
            text: Message text to send

        Returns:
            True if message was sent successfully, False otherwise
        """
        try:
            with ApiClient(self.configuration) as api_client:
                api = MessagingApi(api_client)
                api.reply_message(
                    ReplyMessageRequest(
                        reply_token=reply_token,
                        messages=[TextMessage(text=text)],
                    )
                )
            logger.debug(f"Sent reply: {text[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send LINE reply: {e}")
            return False

    async def reply_messages(
        self,
        reply_token: str,
        texts: list[str],
    ) -> bool:
        """Send multiple text reply messages.

        Args:
            reply_token: Reply token from webhook event
            texts: List of message texts to send (max 5)

        Returns:
            True if messages were sent successfully, False otherwise
        """
        if not texts:
            return False

        # LINE allows max 5 messages per reply
        texts = texts[:5]

        try:
            with ApiClient(self.configuration) as api_client:
                api = MessagingApi(api_client)
                api.reply_message(
                    ReplyMessageRequest(
                        reply_token=reply_token,
                        messages=[TextMessage(text=t) for t in texts],
                    )
                )
            logger.debug(f"Sent {len(texts)} replies")
            return True
        except Exception as e:
            logger.error(f"Failed to send LINE replies: {e}")
            return False

    def parse_events(self, body: str, signature: str) -> list[Any]:
        """Parse webhook events from request body.

        Args:
            body: Request body as string
            signature: X-Line-Signature header value

        Returns:
            List of parsed webhook events

        Raises:
            InvalidSignatureError: If signature is invalid
        """
        return self.parser.parse(body, signature)

    def extract_text_message(self, event: MessageEvent) -> str | None:
        """Extract text content from a message event.

        Args:
            event: LINE message event

        Returns:
            Message text if it's a text message, None otherwise
        """
        if isinstance(event.message, TextMessageContent):
            return event.message.text
        return None

    def get_user_id(self, event: MessageEvent) -> str | None:
        """Extract user ID from a message event.

        Args:
            event: LINE message event

        Returns:
            User ID if available, None otherwise
        """
        if event.source:
            return event.source.user_id
        return None

    async def reply_with_quick_reply(
        self,
        reply_token: str,
        text: str,
        quick_reply: QuickReply,
    ) -> bool:
        """送出附帶 Quick Reply 的文字訊息。

        Args:
            reply_token: Reply token from webhook event
            text: 訊息文字
            quick_reply: Quick Reply 物件

        Returns:
            True if sent successfully
        """
        try:
            with ApiClient(self.configuration) as api_client:
                api = MessagingApi(api_client)
                api.reply_message(
                    ReplyMessageRequest(
                        reply_token=reply_token,
                        messages=[
                            TextMessage(text=text, quick_reply=quick_reply),
                        ],
                    )
                )
            logger.debug(f"Sent reply with quick_reply: {text[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send LINE reply with quick_reply: {e}")
            return False

    def get_reply_token(self, event: MessageEvent) -> str | None:
        """Extract reply token from a message event.

        Args:
            event: LINE message event

        Returns:
            Reply token if available, None otherwise
        """
        return event.reply_token


# ============================================================================
# Quick Reply 輔助函數
# ============================================================================

_MODE_QUICK_REPLY_CONFIG: list[tuple[str, str]] = [
    ("free", "免費"),
    ("cheap", "便宜"),
    ("rigorous", "嚴謹"),
]


def build_mode_quick_replies(current_mode: str) -> QuickReply:
    """建構模式切換 Quick Reply 按鈕。

    當前模式加 ✓ 標記。使用 PostbackAction 避免與一般文字混淆。

    Args:
        current_mode: 目前的 LLM 模式 (cheap/balanced/rigorous)

    Returns:
        QuickReply 物件
    """
    items: list[QuickReplyItem] = []
    for mode_key, label in _MODE_QUICK_REPLY_CONFIG:
        display = f"✓{label}" if mode_key == current_mode else label
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label=display,
                    data=f"action=switch_mode&mode={mode_key}",
                    display_text=f"{label}模式",
                ),
            )
        )
    return QuickReply(items=items)


# Global client instance
_line_client: LineClient | None = None


def get_line_client() -> LineClient:
    """Get singleton LINE client instance."""
    global _line_client
    if _line_client is None:
        _line_client = LineClient()
    return _line_client
