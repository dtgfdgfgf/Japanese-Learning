"""
Unit tests for security library.

T033: Additional unit tests for security
DoD: 測試用戶 ID 雜湊功能
"""

import pytest
from src.lib.security import hash_user_id


class TestHashUserId:
    """Tests for hash_user_id function."""

    def test_hash_produces_fixed_length(self):
        """Test that hash produces fixed-length output."""
        result = hash_user_id("U0123456789abcdef")
        assert len(result) == 64  # SHA-256 hex digest

    def test_hash_is_deterministic(self):
        """Test that same input produces same output."""
        user_id = "U0123456789abcdef"
        result1 = hash_user_id(user_id)
        result2 = hash_user_id(user_id)
        assert result1 == result2

    def test_different_inputs_produce_different_hashes(self):
        """Test that different inputs produce different outputs."""
        result1 = hash_user_id("user1")
        result2 = hash_user_id("user2")
        assert result1 != result2

    def test_hash_is_hex_string(self):
        """Test that hash is a valid hex string."""
        result = hash_user_id("test_user")
        assert all(c in "0123456789abcdef" for c in result)

    def test_empty_string_handling(self):
        """Test empty string raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            hash_user_id("")

    def test_unicode_handling(self):
        """Test Unicode characters are handled correctly."""
        result = hash_user_id("ユーザー123")
        assert len(result) == 64

    def test_line_user_id_format(self):
        """Test typical LINE user ID format."""
        # LINE user IDs are 33 characters starting with U
        line_user_id = "U0123456789abcdef0123456789abcdef"
        result = hash_user_id(line_user_id)
        assert len(result) == 64
        assert result != line_user_id  # Should be different from input
