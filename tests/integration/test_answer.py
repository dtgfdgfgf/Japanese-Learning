"""
Integration tests for answer flow (US4: 作答與判分).

T063: Write integration test for answer flow
DoD: 模擬練習 - 作答完整流程；驗證 practice_log 寫入
"""

import json
import hashlib
import hmac
from unittest.mock import AsyncMock, patch, MagicMock
import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.schemas.practice import PracticeSession, PracticeQuestion, PracticeType
from tests.conftest import create_message_event, create_mock_db_session


class TestAnswerFlowIntegration:
    """Integration tests for the complete answer submission flow."""

    def _create_signature(self, body: bytes, secret: str) -> str:
        """Create LINE signature for testing."""
        return hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256
        ).hexdigest()

    @pytest.mark.asyncio
    async def test_correct_answer_submission(self):
        """Test submitting a correct answer."""
        user_id = "Utest_correct_answer"
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

        with patch("src.api.webhook.get_line_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.verify_signature.return_value = True
            mock_client.reply_message = AsyncMock()
            mock_client.reply_with_quick_reply = AsyncMock()
            mock_client.parse_events.return_value = [
                create_message_event(text="考える", user_id=user_id, reply_token="token1")
            ]

            mock_db = create_mock_db_session()
            with patch("src.api.webhook.get_session") as mock_session:
                mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
                mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

                with patch("src.api.webhook.has_active_session", new_callable=AsyncMock) as mock_has_session:
                    mock_has_session.return_value = True

                    with patch("src.api.webhook._handle_practice_answer") as mock_handle:
                        mock_handle.return_value = "✅ 正確！\n\n下一題：\n2. 「吃」的日文是？"

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
                            mock_handle.assert_called()

    @pytest.mark.asyncio
    async def test_incorrect_answer_submission(self):
        """Test submitting an incorrect answer."""
        user_id = "Utest_incorrect_answer"
        channel_secret = "test_secret_for_testing_only"

        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "wrong_answer"},
                "timestamp": 1625665600000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token1",
                "mode": "active"
            }]
        }).encode("utf-8")

        signature = self._create_signature(body, channel_secret)

        with patch("src.api.webhook.get_line_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.verify_signature.return_value = True
            mock_client.reply_message = AsyncMock()
            mock_client.reply_with_quick_reply = AsyncMock()
            mock_client.parse_events.return_value = [
                create_message_event(text="wrong_answer", user_id=user_id, reply_token="token1")
            ]

            mock_db = create_mock_db_session()
            with patch("src.api.webhook.get_session") as mock_session:
                mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
                mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

                with patch("src.api.webhook.has_active_session", new_callable=AsyncMock) as mock_has_session:
                    mock_has_session.return_value = True

                    with patch("src.api.webhook._handle_practice_answer") as mock_handle:
                        mock_handle.return_value = "❌ 答案是：考える\n\n下一題：\n2. 「吃」的日文是？"

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
                            mock_handle.assert_called()

    @pytest.mark.asyncio
    async def test_session_completion(self):
        """Test when all questions are answered."""
        user_id = "Utest_session_complete"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "last_answer"},
                "timestamp": 1625665600000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": "token1",
                "mode": "active"
            }]
        }).encode("utf-8")
        
        signature = self._create_signature(body, channel_secret)

        with patch("src.api.webhook.get_line_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.verify_signature.return_value = True
            mock_client.reply_message = AsyncMock()
            mock_client.parse_events.return_value = [
                create_message_event(text="last_answer", user_id=user_id, reply_token="token1")
            ]

            with patch("src.api.webhook.has_active_session", new_callable=AsyncMock) as mock_has_session:
                mock_has_session.return_value = True
                
                with patch("src.api.webhook._handle_practice_answer") as mock_handle:
                    mock_handle.return_value = (
                        "✅ 正確！\n\n"
                        "🎉 練習結束！\n"
                        "得分：5/5\n"
                        "太棒了！全部答對！"
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


class TestPracticeLogCreation:
    """Tests for practice log creation during answer submission."""
    
    @pytest.mark.asyncio
    async def test_log_created_on_answer(self, async_db_session):
        """Test that practice_log is created when answer is submitted."""
        from src.services.practice_service import PracticeService
        from src.services.session_service import SessionService

        # Create mock question in session
        mock_question = PracticeQuestion(
            question_id=str(uuid.uuid4()),
            item_id=str(uuid.uuid4()),
            practice_type=PracticeType.VOCAB_RECALL,
            prompt="思考",
            expected_answer="考える",
            item_key="vocab:考える",
        )

        mock_practice_session = PracticeSession(
            session_id=str(uuid.uuid4()),
            user_id="test_user",
            questions=[mock_question],
            current_index=0,
        )

        # Mock SessionService 回傳預設 session
        mock_session_service = MagicMock(spec=SessionService)
        mock_session_service.get_session = AsyncMock(return_value=mock_practice_session)
        mock_session_service.update_session = AsyncMock()
        mock_session_service.clear_session = AsyncMock()

        service = PracticeService.__new__(PracticeService)
        service.session = async_db_session
        service.item_repo = MagicMock()
        service.practice_log_repo = MagicMock()
        service.practice_log_repo.create = AsyncMock()
        service.session_service = mock_session_service

        # Submit correct answer
        answer, message = await service.submit_answer("test_user", "考える")

        # Verify log was created
        service.practice_log_repo.create.assert_called_once()
        call_args = service.practice_log_repo.create.call_args

        assert call_args[1]["user_id"] == "test_user"
        assert call_args[1]["is_correct"] is True

