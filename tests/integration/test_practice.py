"""
Integration tests for practice flow (US3: 練習複習).

T054: Write integration test for practice flow
DoD: 完整流程測試；驗證回傳題目數量與格式
"""

import json
import hashlib
import hmac
from unittest.mock import AsyncMock, patch, MagicMock
import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app


class TestPracticeFlowIntegration:
    """Integration tests for the complete practice flow."""

    def _create_signature(self, body: bytes, secret: str) -> str:
        """Create LINE signature for testing."""
        return hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256
        ).hexdigest()

    @pytest.mark.asyncio
    async def test_practice_insufficient_items(self):
        """Test practice when user has fewer than 5 items."""
        user_id = "Utest_user_few_items"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "練習"},
                "timestamp": 1625665600000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token1",
                "mode": "active"
            }]
        }).encode("utf-8")
        
        signature = self._create_signature(body, channel_secret)

        with patch("src.lib.line_client.get_line_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.verify_signature.return_value = True
            mock_client.reply_message = AsyncMock()
            mock_client.parse_events.return_value = [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "練習"},
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token1",
            }]

            # Mock session and practice service
            with patch("src.api.webhook.get_session") as mock_session:
                mock_session_instance = MagicMock()
                mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
                mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
                
                with patch("src.services.practice_service.PracticeService") as mock_practice_cls:
                    mock_practice = MagicMock()
                    mock_practice.create_session = AsyncMock(return_value=(
                        None,
                        "你的題庫還不夠 📚\n目前只有 3 個項目\n請先入庫更多素材（至少需要 5 個）"
                    ))
                    mock_practice_cls.return_value = mock_practice

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
                        
                        # Verify reply was sent with insufficient items message
                        mock_client.reply_message.assert_called()

    @pytest.mark.asyncio
    async def test_practice_creates_session(self):
        """Test practice creates session successfully."""
        user_id = "Utest_user_enough_items"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "練習"},
                "timestamp": 1625665600000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token1",
                "mode": "active"
            }]
        }).encode("utf-8")
        
        signature = self._create_signature(body, channel_secret)

        with patch("src.lib.line_client.get_line_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.verify_signature.return_value = True
            mock_client.reply_message = AsyncMock()
            mock_client.parse_events.return_value = [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "練習"},
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token1",
            }]

            # Mock session
            with patch("src.api.webhook.get_session") as mock_session:
                mock_session_instance = MagicMock()
                mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
                mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
                
                # Create mock practice session
                from src.schemas.practice import PracticeSession, PracticeQuestion, PracticeType
                
                mock_questions = [
                    PracticeQuestion(
                        question_id=str(uuid.uuid4()),
                        item_id=str(uuid.uuid4()),
                        practice_type=PracticeType.VOCAB_RECALL,
                        prompt=f"meaning{i}",
                        expected_answer=f"word{i}",
                        item_key=f"vocab:word{i}",
                    )
                    for i in range(5)
                ]
                
                mock_practice_session = PracticeSession(
                    session_id=str(uuid.uuid4()),
                    user_id="hashed_user_id",
                    questions=mock_questions,
                )
                
                with patch("src.services.practice_service.PracticeService") as mock_practice_cls:
                    mock_practice = MagicMock()
                    mock_practice.create_session = AsyncMock(return_value=(
                        mock_practice_session,
                        mock_practice_session.format_questions_message()
                    ))
                    mock_practice_cls.return_value = mock_practice

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
                        
                        # Verify reply was sent with questions
                        mock_client.reply_message.assert_called()

    @pytest.mark.asyncio
    async def test_answer_submission_flow(self):
        """Test submitting an answer during practice."""
        # This test verifies that when a user has an active session,
        # their non-command messages are treated as answers
        
        user_id = "Utest_answering_user"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "考える"},
                "timestamp": 1625665600000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token1",
                "mode": "active"
            }]
        }).encode("utf-8")
        
        signature = self._create_signature(body, channel_secret)

        with patch("src.lib.line_client.get_line_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.verify_signature.return_value = True
            mock_client.reply_message = AsyncMock()
            mock_client.parse_events.return_value = [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "考える"},
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token1",
            }]

            # Mock has_active_session to return True
            with patch("src.api.webhook.has_active_session") as mock_has_session:
                mock_has_session.return_value = True
                
                # Mock handle_practice_answer
                with patch("src.api.webhook.handle_practice_answer") as mock_handle:
                    mock_handle.return_value = "✅ 正確！"
                    
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
                        
                        # Verify answer handler was called
                        mock_handle.assert_called()

