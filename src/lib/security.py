"""Security utilities for user data protection.

T096: Implement user_id hashing per NFR-003
DoD: hash_user_id(line_user_id) 使用 SHA-256 + salt；salt 從環境變數讀取
"""

import hashlib
import hmac

from src.config import settings


def hash_user_id(line_user_id: str) -> str:
    """Hash LINE user ID for privacy protection.

    Uses HMAC-SHA256 with a secret salt to create a consistent,
    non-reversible hash of the user ID.

    Args:
        line_user_id: Original LINE user ID

    Returns:
        Hashed user ID (64 character hex string)

    Example:
        >>> hash_user_id("U1234567890abcdef")
        "a1b2c3d4e5f6..."  # 64 char hex
    """
    if not line_user_id:
        raise ValueError("line_user_id cannot be empty")

    # Use HMAC-SHA256 with salt
    hash_bytes = hmac.new(
        key=settings.user_id_salt.encode("utf-8"),
        msg=line_user_id.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()

    # Return as hex string (64 characters)
    return hash_bytes.hex()


def verify_user_id_hash(line_user_id: str, hashed_id: str) -> bool:
    """Verify a LINE user ID matches its hash.

    Args:
        line_user_id: Original LINE user ID
        hashed_id: Previously hashed user ID

    Returns:
        True if the hash matches, False otherwise
    """
    try:
        computed_hash = hash_user_id(line_user_id)
        return hmac.compare_digest(computed_hash, hashed_id)
    except Exception:
        return False
