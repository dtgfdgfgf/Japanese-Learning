"""
Integration tests for search flow (US5: 關鍵字查詢).

T069: Write integration test for search flow in tests/integration/test_search.py
DoD: 完整流程測試；驗證回傳格式正確
"""

import json
import hashlib
import hmac
from unittest.mock import AsyncMock, patch, MagicMock
import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app


class TestSearchFlowIntegration:
    """Integration tests for the search command flow."""

    def _create_signature(self, body: bytes, secret: str) -> str:
        """Create LINE signature for testing."""
        return hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256
        ).hexdigest()

    @pytest.mark.asyncio
    async def test_search_with_results(self):
        """Test search command with matching results."""
        user_id = "Utest_search_results"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "查詢 考える"},
                "timestamp": 1625665600000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token1",
                "mode": "active"
            }]
        }).encode("utf-8")
        
        signature = self._create_signature(body, channel_secret)

        # Mock item results
        mock_items = [
            MagicMock(
                item_id=uuid.uuid4(),
                item_type="vocab",
                payload={"surface": "考える", "reading": "かんがえる", "glossary_zh": ["思考"]},
            ),
            MagicMock(
                item_id=uuid.uuid4(),
                item_type="vocab",
                payload={"surface": "考え方", "reading": "かんがえかた", "glossary_zh": ["想法"]},
            ),
        ]

        with patch("src.api.webhook.get_line_client") as mock_line:
            mock_client = MagicMock()
            mock_client.verify_signature.return_value = True
            mock_client.reply_message = AsyncMock()
            mock_line.return_value = mock_client
            
            with patch("src.api.webhook.get_session") as mock_session_ctx:
                mock_session = AsyncMock()
                mock_session_ctx.return_value.__aenter__.return_value = mock_session
                
                with patch("src.repositories.item_repo.ItemRepository.search_by_keyword") as mock_search:
                    mock_search.return_value = mock_items
                    
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

    @pytest.mark.asyncio
    async def test_search_no_results(self):
        """Test search command with no matching results."""
        user_id = "Utest_search_no_results"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "查詢 不存在的詞"},
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
            
            with patch("src.api.webhook.get_session") as mock_session_ctx:
                mock_session = AsyncMock()
                mock_session_ctx.return_value.__aenter__.return_value = mock_session
                
                with patch("src.repositories.item_repo.ItemRepository.search_by_keyword") as mock_search:
                    mock_search.return_value = []
                    
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

    @pytest.mark.asyncio
    async def test_search_without_keyword(self):
        """Test search command without keyword."""
        user_id = "Utest_search_no_keyword"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "查詢"},
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
                
                # Should prompt user to provide keyword
                # The actual message is sent via reply_message

    @pytest.mark.asyncio
    async def test_search_with_many_results(self):
        """Test search command with more than 5 results."""
        user_id = "Utest_search_many"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "查詢 る"},
                "timestamp": 1625665600000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token1",
                "mode": "active"
            }]
        }).encode("utf-8")
        
        signature = self._create_signature(body, channel_secret)

        # Create 8 mock items
        mock_items = [
            MagicMock(
                item_id=uuid.uuid4(),
                item_type="vocab",
                payload={"surface": f"動詞{i}", "reading": f"どうし{i}", "glossary_zh": [f"動詞{i}"]},
            )
            for i in range(8)
        ]

        with patch("src.api.webhook.get_line_client") as mock_line:
            mock_client = MagicMock()
            mock_client.verify_signature.return_value = True
            mock_client.reply_message = AsyncMock()
            mock_line.return_value = mock_client
            
            with patch("src.api.webhook.get_session") as mock_session_ctx:
                mock_session = AsyncMock()
                mock_session_ctx.return_value.__aenter__.return_value = mock_session
                
                with patch("src.repositories.item_repo.ItemRepository.search_by_keyword") as mock_search:
                    mock_search.return_value = mock_items
                    
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
