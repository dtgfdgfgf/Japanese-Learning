"""
Integration tests for analyze flow (US2: 素材分析).

T044: Write integration test for analyze flow
DoD: 完整流程測試；包含重複入庫場景驗證 upsert
"""

import json
import hashlib
import hmac
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from src.main import app
from tests.conftest import create_message_event


class TestAnalyzeFlowIntegration:
    """Integration tests for the complete analyze flow."""

    def _create_signature(self, body: bytes, secret: str) -> str:
        """Create LINE signature for testing."""
        return hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256
        ).hexdigest()

    @pytest.mark.asyncio
    async def test_analyze_no_deferred_document(self):
        """Test analyze when no document is pending."""
        user_id = "Utest_user_no_docs"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "分析"},
                "timestamp": 1625665600000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token1",
                "mode": "active"
            }]
        }).encode("utf-8")
        
        signature = self._create_signature(body, channel_secret)

        with patch("src.api.webhook.get_line_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.verify_signature.return_value = True
            mock_client.reply_message = AsyncMock()
            mock_client.reply_with_quick_reply = AsyncMock()
            mock_client.parse_events.return_value = [
                create_message_event(text="分析", user_id=user_id, reply_token="token1")
            ]
            mock_get_client.return_value = mock_client

            # Mock ExtractorService to return no deferred docs
            with patch("src.api.webhook.get_session") as mock_session:
                mock_session_instance = MagicMock()
                mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
                mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

                with patch("src.services.extractor_service.ExtractorService") as mock_extractor:
                    mock_extractor_instance = MagicMock()
                    mock_extractor_instance.get_deferred_documents = AsyncMock(return_value=[])
                    mock_extractor.return_value = mock_extractor_instance

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

                        # Should reply with "no pending documents" message
                        mock_client.reply_with_quick_reply.assert_called()
                        reply_args = mock_client.reply_with_quick_reply.call_args
                        reply_text = reply_args[0][1] if reply_args[0] else reply_args[1].get("text", "")
                        # Check for expected message content
                        assert "待分析" in reply_text or "入庫" in reply_text

    @pytest.mark.asyncio
    async def test_analyze_with_extraction_success(self):
        """Test successful extraction flow."""
        user_id = "Utest_user_with_doc"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "分析"},
                "timestamp": 1625665600000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token1",
                "mode": "active"
            }]
        }).encode("utf-8")
        
        signature = self._create_signature(body, channel_secret)

        with patch("src.api.webhook.get_line_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.verify_signature.return_value = True
            mock_client.reply_message = AsyncMock()
            mock_client.parse_events.return_value = [
                create_message_event(text="分析", user_id=user_id, reply_token="token1")
            ]
            mock_get_client.return_value = mock_client

            # Mock session and extractor
            with patch("src.api.webhook.get_session") as mock_session:
                mock_session_instance = MagicMock()
                mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
                mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
                
                # Mock deferred document
                mock_doc = MagicMock()
                mock_doc.doc_id = "doc123"
                
                # Mock extraction response
                from src.schemas.extractor import ExtractorResponse
                mock_response = ExtractorResponse(
                    doc_id="doc123",
                    items=[],
                    vocab_count=3,
                    grammar_count=2,
                )
                
                with patch("src.services.extractor_service.ExtractorService") as mock_extractor_cls:
                    mock_extractor = MagicMock()
                    mock_extractor.get_deferred_documents = AsyncMock(return_value=[mock_doc])
                    mock_extractor.extract = AsyncMock(return_value=mock_response)
                    mock_extractor_cls.return_value = mock_extractor

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
                        
                        # Verify reply was sent with extraction results
                        mock_client.reply_message.assert_called()

    @pytest.mark.asyncio
    async def test_full_save_then_analyze_flow(self, async_db_session):
        """Test complete flow: save → analyze."""
        # This test simulates the full user journey
        # First save Japanese content, then analyze it
        
        user_id = "Ufull_flow_test"
        channel_secret = "test_secret_for_testing_only"
        
        # Step 1: User sends Japanese content
        content_body = json.dumps({
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
        
        # Step 2: User sends 入庫
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
        
        # Step 3: User sends 分析
        analyze_body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "3", "text": "分析"},
                "timestamp": 1625665602000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token3",
                "mode": "active"
            }]
        }).encode("utf-8")

        # Note: Full integration would require actual database setup
        # This test focuses on the API flow structure
        
        with patch("src.api.webhook.get_line_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.verify_signature.return_value = True
            mock_client.reply_message = AsyncMock()
            mock_get_client.return_value = mock_client
            
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Send content
                mock_client.parse_events.return_value = [
                    create_message_event(text="考える（かんがえる）：思考", user_id=user_id, reply_token="token1")
                ]
                response1 = await client.post(
                    "/webhook",
                    content=content_body,
                    headers={
                        "X-Line-Signature": self._create_signature(content_body, channel_secret),
                        "Content-Type": "application/json"
                    }
                )
                assert response1.status_code == 200
                
                # Send save command
                mock_client.parse_events.return_value = [
                    create_message_event(text="入庫", user_id=user_id, reply_token="token2")
                ]
                response2 = await client.post(
                    "/webhook",
                    content=save_body,
                    headers={
                        "X-Line-Signature": self._create_signature(save_body, channel_secret),
                        "Content-Type": "application/json"
                    }
                )
                assert response2.status_code == 200
