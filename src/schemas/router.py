"""
Pydantic schemas for Router Service.

T080: Create Pydantic schemas for Router in src/schemas/router.py
DoD: RouterRequest, RouterResponse schemas 符合 plan.md Router Output
"""

from enum import Enum
from pydantic import BaseModel, Field


class IntentType(str, Enum):
    """Possible intents from Router classification."""
    
    SAVE = "save"           # User wants to save content
    PRACTICE = "practice"   # User wants to practice
    SEARCH = "search"       # User wants to search
    DELETE = "delete"       # User wants to delete
    HELP = "help"           # User needs help
    CHAT = "chat"           # General chat/learning question
    UNKNOWN = "unknown"     # Cannot determine intent


class RouterRequest(BaseModel):
    """Request to Router for intent classification."""
    
    message: str = Field(..., description="User's message text")
    context: str | None = Field(
        default=None, 
        description="Optional context from previous messages"
    )


class RouterResponse(BaseModel):
    """Response from Router with classified intent."""
    
    intent: IntentType = Field(..., description="Classified intent")
    confidence: float = Field(
        ..., 
        ge=0.0, 
        le=1.0, 
        description="Confidence score (0-1)"
    )
    keyword: str | None = Field(
        default=None,
        description="Extracted keyword for search intent"
    )
    reason: str | None = Field(
        default=None,
        description="Explanation for classification"
    )
    suggested_response: str | None = Field(
        default=None,
        description="Suggested response for chat intent"
    )
    
    @property
    def is_confident(self) -> bool:
        """Check if confidence is above threshold."""
        return self.confidence >= 0.7
    
    @property
    def needs_fallback(self) -> bool:
        """Check if fallback action is needed."""
        return self.confidence < 0.5 or self.intent == IntentType.UNKNOWN


class RouterClassification(BaseModel):
    """Internal classification result from LLM."""
    
    intent: str = Field(..., description="Intent string from LLM")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence value")
    keyword: str | None = Field(default=None)
    reason: str | None = Field(default=None)
    
    def to_response(self) -> RouterResponse:
        """Convert to RouterResponse with validated intent."""
        try:
            intent_type = IntentType(self.intent.lower())
        except ValueError:
            intent_type = IntentType.UNKNOWN
        
        return RouterResponse(
            intent=intent_type,
            confidence=self.confidence,
            keyword=self.keyword,
            reason=self.reason,
        )
