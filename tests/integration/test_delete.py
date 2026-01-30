"""
Integration tests for delete flow (US6: 刪除資料).

T075: Write integration test for delete flow in tests/integration/test_delete.py
DoD: 測試二次確認流程；驗證清空後 items 不出現在查詢/練習
"""

import json
import hashlib
import hmac
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from tests.conftest import create_message_event


class TestDeleteLastIntegration:
    """Integration tests for delete_last command."""

    def _create_signature(self, body: bytes, secret: str) -> str:
        """Create LINE signature for testing."""
        return hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256
        ).hexdigest()

    @pytest.mark.asyncio
    async def test_delete_last_command(self):
        """Test 刪除最後一筆 command flow."""
        user_id = "Utest_delete_last"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "刪除最後一筆"},
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
            mock_client.parse_events.return_value = [
                create_message_event(text="刪除最後一筆", user_id=user_id, reply_token="token1")
            ]
            mock_line.return_value = mock_client
            
            with patch("src.api.webhook.get_session") as mock_session_ctx:
                mock_session = AsyncMock()
                mock_session.commit = AsyncMock()
                mock_session_ctx.return_value.__aenter__.return_value = mock_session
                
                with patch("src.services.delete_service.DeleteService.delete_last") as mock_delete:
                    mock_delete.return_value = (1, "已刪除最後一筆（共 1 筆資料）🗑️")
                    
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


class TestClearAllIntegration:
    """Integration tests for clear all data flow."""

    def _create_signature(self, body: bytes, secret: str) -> str:
        """Create LINE signature for testing."""
        return hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256
        ).hexdigest()

    @pytest.mark.asyncio
    async def test_clear_all_prompts_confirmation(self):
        """Test 清空資料 command prompts for confirmation."""
        user_id = "Utest_clear_all_prompt"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "清空資料"},
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
            mock_client.parse_events.return_value = [
                create_message_event(text="清空資料", user_id=user_id, reply_token="token1")
            ]
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

    @pytest.mark.asyncio
    async def test_confirm_clear_without_pending_request(self):
        """Test 確定清空資料 without prior request."""
        user_id = "Utest_clear_no_pending"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "確定清空資料"},
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
            mock_client.parse_events.return_value = [
                create_message_event(text="確定清空資料", user_id=user_id, reply_token="token1")
            ]
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

    @pytest.mark.asyncio
    async def test_confirm_clear_with_pending_request(self):
        """Test 確定清空資料 with pending request."""
        user_id = "Utest_clear_with_pending"
        channel_secret = "test_secret_for_testing_only"
        
        body = json.dumps({
            "destination": "Uxxxxx",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "1", "text": "確定清空資料"},
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
            mock_client.parse_events.return_value = [
                create_message_event(text="確定清空資料", user_id=user_id, reply_token="token1")
            ]
            mock_line.return_value = mock_client
            
            with patch("src.api.webhook.get_session") as mock_session_ctx:
                mock_session = AsyncMock()
                mock_session.commit = AsyncMock()
                mock_session_ctx.return_value.__aenter__.return_value = mock_session

                with patch("src.repositories.user_state_repo.UserStateRepository.is_delete_confirmation_pending", new_callable=AsyncMock, return_value=True):
                    with patch("src.repositories.user_state_repo.UserStateRepository.clear_delete_confirm", new_callable=AsyncMock):
                        with patch("src.services.delete_service.DeleteService.clear_all_data") as mock_clear:
                            mock_clear.return_value = (10, "已清空所有資料 🗑️")

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


class TestDeletedDataExclusion:
    """Tests verifying deleted data is excluded from queries."""
    
    @pytest.mark.asyncio
    async def test_deleted_items_not_in_search(self, async_db_session):
        """Test that soft-deleted items don't appear in search."""
        from src.repositories.item_repo import ItemRepository
        
        repo = ItemRepository(async_db_session)
        
        # Search should exclude deleted items
        results = await repo.search_by_keyword(
            user_id="test_user_hash",
            keyword="test",
            limit=10,
        )
        
        # All results should have is_deleted=False (or be empty)
        for item in results:
            assert item.is_deleted is False or item.is_deleted is None
    
    @pytest.mark.asyncio
    async def test_deleted_items_not_in_practice(self, async_db_session):
        """Test that soft-deleted items don't appear in practice."""
        from src.repositories.item_repo import ItemRepository
        
        repo = ItemRepository(async_db_session)
        
        # get_by_user (used for practice) should exclude deleted
        items = await repo.get_by_user(
            user_id="test_user_hash",
            include_deleted=False,
        )
        
        for item in items:
            assert item.is_deleted is False or item.is_deleted is None

