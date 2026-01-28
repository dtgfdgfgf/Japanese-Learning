"""
Integration tests for privacy command (US7: 隱私資訊查詢).

T079: Write integration test for privacy command in tests/integration/test_privacy.py
DoD: 驗證回覆內容包含必要資訊
"""

import json
import hashlib
import hmac
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.services.command_service import get_privacy_message


class TestPrivacyCommandIntegration:
    """Integration tests for the privacy command."""

    def _create_signature(self, body: bytes, secret: str) -> str:
        """Create LINE signature for testing."""
        return hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256
        ).hexdigest()

    @pytest.mark.asyncio
    async def test_privacy_command_returns_policy(self):
        """Test 隱私 command returns privacy policy."""
        user_id = "Utest_privacy"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "隱私"},
                "timestamp": 1625665600000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token1",
                "mode": "active"
            }]
        }).encode("utf-8")
        
        signature = self._create_signature(body, channel_secret)

        with patch("src.api.webhook.get_line_client") as mock_line:
            mock_client = MagicMock()
            mock_client.verify_signature.return_value = True
            mock_client.reply_message = AsyncMock()
            mock_line.return_value = mock_client
            
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/webhook",
                    content=body,
                    headers={
                        "X-Line-Signature": signature,
                        "Content-Type": "application/json"
                    }
                )
                assert response.status_code == 200
                
                # Verify reply_message was called
                mock_client.reply_message.assert_called_once()


class TestPrivacyContent:
    """Tests for privacy message content."""
    
    def test_privacy_contains_data_storage_info(self):
        """Test privacy message mentions data storage."""
        message = get_privacy_message()
        
        # Should mention data storage
        assert any(term in message for term in ["資料保存", "保存", "儲存", "資料"])
    
    def test_privacy_contains_ai_usage_info(self):
        """Test privacy message mentions AI usage."""
        message = get_privacy_message()
        
        # Should mention AI usage
        assert any(term in message for term in ["AI", "AI 使用", "人工智慧"])
    
    def test_privacy_contains_deletion_info(self):
        """Test privacy message mentions data deletion."""
        message = get_privacy_message()
        
        # Should mention how to delete data
        assert any(term in message for term in ["刪除", "刪除最後一筆", "清空資料"])
    
    def test_privacy_contains_user_id_handling(self):
        """Test privacy message mentions user ID handling."""
        message = get_privacy_message()
        
        # Should mention LINE ID or user ID handling
        assert any(term in message for term in ["LINE ID", "ID", "雜湊", "加密"])
    
    def test_privacy_length_within_line_limit(self):
        """Test privacy message doesn't exceed LINE message limit."""
        message = get_privacy_message()
        
        # LINE text message limit is 5000 characters
        # But for readability, should be much shorter
        assert len(message) <= 2000
    
    def test_privacy_has_clear_formatting(self):
        """Test privacy message has clear formatting."""
        message = get_privacy_message()
        
        # Should have some structure (bullet points, sections, etc.)
        assert any(char in message for char in ["•", "📦", "🤖", "🗑️", ":", "："])


class TestPrivacyVariants:
    """Test different ways to trigger privacy command."""
    
    @pytest.mark.asyncio
    async def test_privacy_alias_command(self):
        """Test privacy command with alias."""
        # The command parser should handle variations
        from src.services.command_service import parse_command
        from src.schemas.command import CommandType
        
        # Standard command
        result = parse_command("隱私")
        assert result.command_type == CommandType.PRIVACY
        
        # With spaces
        result = parse_command("  隱私  ")
        assert result.command_type == CommandType.PRIVACY

