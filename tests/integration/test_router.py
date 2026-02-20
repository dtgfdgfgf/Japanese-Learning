"""
Integration tests for Router flow.

T088: Write integration test for router flow in tests/integration/test_router.py
DoD: 完整流程測試；驗證非指令訊息正確路由
"""

import json
import hashlib
import hmac
from unittest.mock import AsyncMock, patch, MagicMock
import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.schemas.router import IntentType, RouterResponse


class TestRouterFlowIntegration:
    """Integration tests for Router-based message handling."""

    def _create_signature(self, body: bytes, secret: str) -> str:
        """Create LINE signature for testing."""
        return hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256
        ).hexdigest()

    @pytest.mark.asyncio
    async def test_auto_save_high_confidence(self):
        """Test auto-save for high confidence save intent."""
        user_id = "Utest_auto_save"
        channel_secret = "test_secret_for_testing_only"
        
        # Japanese content that should trigger auto-save
        japanese_text = "今日は天気がいいですね。散歩に行きましょう。"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": japanese_text},
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
            
            with patch("src.services.router_service.RouterService.classify") as mock_classify:
                mock_classify.return_value = (RouterResponse(
                    intent=IntentType.SAVE,
                    confidence=0.85,
                    reason="Japanese content"
                ), None)
                
                with patch("src.api.webhook.get_session") as mock_session_ctx:
                    mock_session = AsyncMock()
                    mock_session_ctx.return_value.__aenter__.return_value = mock_session
                    
                    with patch("src.services.command_service.CommandService.save_raw") as mock_save:
                        mock_save.return_value = MagicMock(
                            message="已入庫：#abc12345"
                        )
                        
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
    async def test_chat_response_for_questions(self):
        """Test chat response for learning questions."""
        user_id = "Utest_chat"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "這個文法怎麼用？"},
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
            
            with patch("src.services.router_service.RouterService.classify") as mock_classify:
                mock_classify.return_value = (RouterResponse(
                    intent=IntentType.CHAT,
                    confidence=0.7,
                    reason="Learning question"
                ), None)

                with patch("src.services.router_service.RouterService.get_chat_response") as mock_chat:
                    mock_chat_resp = MagicMock()
                    mock_chat_resp.content = "這個文法表示..."
                    mock_chat_resp.to_trace.return_value = MagicMock()
                    mock_chat.return_value = mock_chat_resp
                    
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
    async def test_search_via_router(self):
        """Test search triggered via Router intent."""
        user_id = "Utest_router_search"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "找一下考える"},
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
            
            with patch("src.services.router_service.RouterService.classify") as mock_classify:
                mock_classify.return_value = (RouterResponse(
                    intent=IntentType.SEARCH,
                    confidence=0.8,
                    keyword="考える",
                    reason="Search request"
                ), None)
                
                with patch("src.api.webhook.get_session") as mock_session_ctx:
                    mock_session = AsyncMock()
                    mock_session_ctx.return_value.__aenter__.return_value = mock_session
                    
                    with patch("src.repositories.item_repo.ItemRepository.search_by_keyword") as mock_search:
                        mock_search.return_value = []  # No results
                        
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
    async def test_fallback_for_low_confidence(self):
        """Test fallback message for low confidence classification."""
        user_id = "Utest_fallback"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "ok"},
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
            
            with patch("src.services.router_service.RouterService.classify") as mock_classify:
                mock_classify.return_value = (RouterResponse(
                    intent=IntentType.UNKNOWN,
                    confidence=0.3,
                    reason="Cannot determine"
                ), None)
                
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
    async def test_router_error_graceful_fallback(self):
        """Test graceful fallback when Router errors."""
        user_id = "Utest_router_error"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "test"},
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
            
            with patch("src.services.router_service.RouterService.classify") as mock_classify:
                mock_classify.side_effect = Exception("Router error")
                
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
                    # Should still return 200, not crash
                    assert response.status_code == 200
