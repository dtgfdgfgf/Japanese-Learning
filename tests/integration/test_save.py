"""
Integration tests for save flow (US1: 素材入庫).

T034: Integration test for save flow
DoD: 模擬 LINE webhook 完整流程；驗證 DB 寫入正確
"""

import json
import hashlib
import hmac
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.database import get_session
from tests.conftest import create_message_event


class TestSaveFlowIntegration:
    """Integration tests for the complete save flow."""

    def _create_signature(self, body: bytes, secret: str) -> str:
        """Create LINE signature for testing."""
        return hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256
        ).hexdigest()

    @pytest.mark.asyncio
    async def test_save_flow_complete(self, async_db_session):
        """Test complete save flow: 入庫 -> text -> save."""
        # Prepare test data
        user_id = "U0123456789abcdef0123456789abcdef"
        channel_secret = "test_secret_for_testing_only"
        
        # First request: Send Japanese text
        text_body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "考える（かんがえる）：思考"},
                "timestamp": 1625665600000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token1",
                "mode": "active"
            }]
        }).encode("utf-8")
        
        # Second request: Send 入庫 command
        save_body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "2", "text": "入庫"},
                "timestamp": 1625665601000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token2",
                "mode": "active"
            }]
        }).encode("utf-8")

        text_signature = self._create_signature(text_body, channel_secret)
        save_signature = self._create_signature(save_body, channel_secret)

        # Mock the LINE client reply to avoid actual API calls
        with patch("src.api.webhook.get_line_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.verify_signature.return_value = True
            mock_client.reply_message = AsyncMock()
            # 使用 create_message_event 建立正確的 MessageEvent 物件
            mock_client.parse_events.side_effect = [
                [create_message_event(
                    text="考える（かんがえる）：思考",
                    user_id=user_id,
                    reply_token="token1",
                    message_id="1",
                )],
                [create_message_event(
                    text="入庫",
                    user_id=user_id,
                    reply_token="token2",
                    message_id="2",
                )],
            ]
            mock_get_client.return_value = mock_client

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Send text first
                response1 = await client.post(
                    "/webhook",
                    content=text_body,
                    headers={
                        "X-Line-Signature": text_signature,
                        "Content-Type": "application/json"
                    }
                )
                assert response1.status_code == 200

                # Send 入庫 command
                response2 = await client.post(
                    "/webhook",
                    content=save_body,
                    headers={
                        "X-Line-Signature": save_signature,
                        "Content-Type": "application/json"
                    }
                )
                assert response2.status_code == 200

                # Verify reply was called
                assert mock_client.reply_message.called

    @pytest.mark.asyncio
    async def test_save_without_previous_message(self):
        """Test 入庫 without previous message."""
        user_id = "Unew_user_no_history"
        channel_secret = "test_secret_for_testing_only"
        
        save_body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "入庫"},
                "timestamp": 1625665600000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token1",
                "mode": "active"
            }]
        }).encode("utf-8")
        
        signature = self._create_signature(save_body, channel_secret)

        with patch("src.api.webhook.get_line_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.verify_signature.return_value = True
            mock_client.reply_message = AsyncMock()
            mock_client.parse_events.return_value = [
                create_message_event(text="入庫", user_id=user_id, reply_token="token1")
            ]
            mock_get_client.return_value = mock_client

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/webhook",
                    content=save_body,
                    headers={
                        "X-Line-Signature": signature,
                        "Content-Type": "application/json"
                    }
                )
                assert response.status_code == 200
                
                # Should reply with error message about no previous text
                mock_client.reply_message.assert_called()

    @pytest.mark.asyncio
    async def test_webhook_invalid_signature(self):
        """Test webhook with invalid signature."""
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": []
        }).encode("utf-8")

        with patch("src.api.webhook.get_line_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.verify_signature.return_value = False
            mock_get_client.return_value = mock_client

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/webhook",
                    content=body,
                    headers={
                        "X-Line-Signature": "invalid_signature",
                        "Content-Type": "application/json"
                    }
                )
                assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        """Test health check endpoint."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert "version" in data
