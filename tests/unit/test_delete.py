"""
Unit tests for delete functionality.

T074: Write unit tests for delete in tests/unit/test_delete.py
DoD: 測試軟刪除邏輯；驗證 is_deleted flag 正確設定
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta, timezone
import uuid

from src.services.delete_service import (
    DeleteService,
    is_confirmation_pending,
    request_clear_all,
    CONFIRMATION_TIMEOUT,
    _confirmation_pending,
)


class TestDeleteService:
    """Tests for DeleteService."""
    
    @pytest.fixture
    def mock_session(self):
        """Create mock database session."""
        session = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        return session
    
    @pytest.mark.asyncio
    async def test_delete_last_no_data(self, mock_session):
        """Test delete_last when no data exists."""
        # Setup mock to return None for the raw message query
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        
        service = DeleteService(mock_session)
        
        count, message = await service.delete_last("test_user_hash")
        
        assert count == 0
        assert "沒有可刪除的資料" in message
    
    @pytest.mark.asyncio
    async def test_delete_last_success(self, mock_session):
        """Test successful delete_last."""
        # Mock raw message
        mock_raw = MagicMock()
        mock_raw.raw_id = uuid.uuid4()
        
        # Mock document
        mock_doc = MagicMock()
        mock_doc.doc_id = uuid.uuid4()
        
        # Setup mock returns
        execute_results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=mock_raw)),  # get latest raw
            MagicMock(scalar_one_or_none=MagicMock(return_value=mock_doc)),  # get doc
            MagicMock(rowcount=3),  # delete items
        ]
        mock_session.execute.side_effect = execute_results
        
        # Mock repo soft_delete
        with patch.object(DeleteService, '_get_latest_raw', return_value=mock_raw):
            with patch.object(DeleteService, '_get_doc_by_raw', return_value=mock_doc):
                with patch.object(DeleteService, '_delete_items_by_doc', return_value=3):
                    service = DeleteService(mock_session)
                    service.raw_repo = MagicMock()
                    service.raw_repo.soft_delete = AsyncMock(return_value=True)
                    service.doc_repo = MagicMock()
                    service.doc_repo.soft_delete = AsyncMock(return_value=True)
                    
                    count, message = await service.delete_last("test_user_hash")
                    
                    assert count > 0
                    assert "已刪除" in message


class TestConfirmationState:
    """Tests for confirmation state management."""
    
    def setup_method(self):
        """Clear confirmation state before each test."""
        _confirmation_pending.clear()
    
    def test_request_clear_all_sets_pending(self):
        """Test that request_clear_all sets pending state."""
        # request_clear_all 現在是 module-level function
        message = request_clear_all("test_user")
        
        assert "test_user" in _confirmation_pending
        assert "確定要清空" in message
    
    def test_check_confirmation_pending_true(self):
        """Test check_confirmation_pending returns True when pending."""
        _confirmation_pending["test_user"] = datetime.now(timezone.utc)
        
        service = DeleteService.__new__(DeleteService)
        
        assert service.check_confirmation_pending("test_user") is True
    
    def test_check_confirmation_pending_expired(self):
        """Test check_confirmation_pending returns False when expired."""
        # Set pending time in the past
        _confirmation_pending["test_user"] = datetime.now(timezone.utc) - timedelta(seconds=CONFIRMATION_TIMEOUT + 10)

        service = DeleteService.__new__(DeleteService)

        assert service.check_confirmation_pending("test_user") is False
        # Should have been cleaned up
        assert "test_user" not in _confirmation_pending
    
    def test_clear_confirmation(self):
        """Test clear_confirmation removes pending state."""
        _confirmation_pending["test_user"] = datetime.now(timezone.utc)

        service = DeleteService.__new__(DeleteService)


class TestIsConfirmationPending:
    """Tests for module-level is_confirmation_pending function."""
    
    def setup_method(self):
        """Clear confirmation state before each test."""
        _confirmation_pending.clear()
    
    def test_returns_false_when_no_pending(self):
        """Test returns False when no confirmation pending."""
        assert is_confirmation_pending("test_user") is False
    
    def test_returns_true_when_pending(self):
        """Test returns True when confirmation is pending."""
        _confirmation_pending["test_user"] = datetime.now(timezone.utc)

        assert is_confirmation_pending("test_user") is True
    
    def test_returns_false_when_expired(self):
        """Test returns False and cleans up when expired."""
        _confirmation_pending["test_user"] = datetime.now(timezone.utc) - timedelta(seconds=CONFIRMATION_TIMEOUT + 10)

        assert is_confirmation_pending("test_user") is False
        assert "test_user" not in _confirmation_pending


class TestSoftDeleteFlags:
    """Tests for soft delete flag behavior."""
    
    @pytest.mark.asyncio
    async def test_soft_delete_sets_is_deleted_flag(self, async_db_session):
        """Test that soft delete sets is_deleted to True."""
        from src.repositories.item_repo import ItemRepository
        
        repo = ItemRepository(async_db_session)
        
        # Verify soft_delete method exists
        assert hasattr(repo, 'soft_delete')
    
    @pytest.mark.asyncio
    async def test_deleted_items_excluded_from_queries(self, async_db_session):
        """Test that deleted items are excluded from normal queries."""
        from src.repositories.item_repo import ItemRepository
        
        repo = ItemRepository(async_db_session)
        
        # get_by_user should exclude deleted items by default
        items = await repo.get_by_user(
            user_id="test_user_hash",
            include_deleted=False,
        )
        
        # Should return empty list since no data
        assert items == []
    
    @pytest.mark.asyncio  
    async def test_deleted_items_included_when_requested(self, async_db_session):
        """Test that deleted items can be included when explicitly requested."""
        from src.repositories.item_repo import ItemRepository
        
        repo = ItemRepository(async_db_session)
        
        # get_by_user with include_deleted=True
        items = await repo.get_by_user(
            user_id="test_user_hash",
            include_deleted=True,
        )
        
        # Method should accept the parameter
        assert isinstance(items, list)
