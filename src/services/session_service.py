"""
Session service for managing practice session state.

T057: Create practice session state tracking in src/services/session_service.py
DoD: SessionService 可 get/set 當前 session；支援 in-memory 或 Redis backend
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from src.schemas.practice import PracticeSession


logger = logging.getLogger(__name__)

# In-memory session store
# Key: user_id (hashed), Value: PracticeSession
_sessions: dict[str, PracticeSession] = {}

# Session expiration time (30 minutes)
SESSION_EXPIRATION_MINUTES = 30


class SessionService:
    """Service for managing user session state.
    
    Currently uses in-memory storage. For production, 
    this should be replaced with Redis or database-backed storage.
    """
    
    @staticmethod
    def get_session(user_id: str) -> Optional[PracticeSession]:
        """Get active session for a user.
        
        Args:
            user_id: Hashed user ID
            
        Returns:
            PracticeSession if exists and not expired, None otherwise
        """
        session = _sessions.get(user_id)
        
        if not session:
            return None
        
        # Check expiration
        expiration = session.created_at + timedelta(minutes=SESSION_EXPIRATION_MINUTES)
        if datetime.utcnow() > expiration:
            logger.info(f"Session expired for user {user_id[:8]}")
            del _sessions[user_id]
            return None
        
        # Check if complete
        if session.is_complete:
            return None
        
        return session
    
    @staticmethod
    def set_session(user_id: str, session: PracticeSession) -> None:
        """Store a session for a user.
        
        Args:
            user_id: Hashed user ID
            session: PracticeSession to store
        """
        _sessions[user_id] = session
        logger.debug(f"Stored session {session.session_id} for user {user_id[:8]}")
    
    @staticmethod
    def clear_session(user_id: str) -> bool:
        """Clear a user's session.
        
        Args:
            user_id: Hashed user ID
            
        Returns:
            True if session was cleared, False if no session existed
        """
        if user_id in _sessions:
            del _sessions[user_id]
            logger.debug(f"Cleared session for user {user_id[:8]}")
            return True
        return False
    
    @staticmethod
    def has_active_session(user_id: str) -> bool:
        """Check if user has an active session.
        
        Args:
            user_id: Hashed user ID
            
        Returns:
            True if active session exists
        """
        return SessionService.get_session(user_id) is not None
    
    @staticmethod
    def cleanup_expired_sessions() -> int:
        """Remove all expired sessions.
        
        Returns:
            Number of sessions cleaned up
        """
        now = datetime.utcnow()
        expired_users = []
        
        for user_id, session in _sessions.items():
            expiration = session.created_at + timedelta(minutes=SESSION_EXPIRATION_MINUTES)
            if now > expiration or session.is_complete:
                expired_users.append(user_id)
        
        for user_id in expired_users:
            del _sessions[user_id]
        
        if expired_users:
            logger.info(f"Cleaned up {len(expired_users)} expired sessions")
        
        return len(expired_users)
    
    @staticmethod
    def get_active_session_count() -> int:
        """Get count of active sessions.
        
        Returns:
            Number of active sessions
        """
        return len(_sessions)


# Convenience functions for backward compatibility with practice_service
def get_active_session(user_id: str) -> Optional[PracticeSession]:
    """Get active session (convenience function)."""
    return SessionService.get_session(user_id)


def has_active_session(user_id: str) -> bool:
    """Check if user has active session (convenience function)."""
    return SessionService.has_active_session(user_id)


def clear_session(user_id: str) -> None:
    """Clear user session (convenience function)."""
    SessionService.clear_session(user_id)
