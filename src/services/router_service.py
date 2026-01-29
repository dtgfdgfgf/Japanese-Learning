"""
Router service for LLM-based intent classification.

T082: Implement RouterService in src/services/router_service.py
DoD: classify(message) 回傳 RouterResponse；confidence < 0.5 觸發 fallback
"""

import json
import logging
from typing import Optional

from src.lib.llm_client import get_llm_client
from src.prompts.router import format_router_request, get_system_prompt
from src.schemas.router import IntentType, RouterResponse, RouterClassification
from src.templates.messages import Messages


logger = logging.getLogger(__name__)

# Confidence thresholds
HIGH_CONFIDENCE_THRESHOLD = 0.8
LOW_CONFIDENCE_THRESHOLD = 0.5


class RouterService:
    """Service for classifying user intent using LLM."""
    
    def __init__(self):
        """Initialize RouterService."""
        self.llm_client = get_llm_client()
    
    async def classify(
        self,
        message: str,
        context: Optional[str] = None,
        mode: str = "balanced",
    ) -> RouterResponse:
        """Classify user message intent.

        Args:
            message: User's message
            context: Optional conversation context
            mode: LLM mode (cheap/balanced/rigorous)

        Returns:
            RouterResponse with classified intent
        """
        try:
            user_prompt = format_router_request(message, context)
            system_prompt = get_system_prompt()

            response = await self.llm_client.complete_with_mode(
                mode=mode,
                system_prompt=system_prompt,
                user_message=user_prompt,
                temperature=0.3,
                max_tokens=500,
            )
            response_text = response.content
            
            # Parse response
            return self._parse_llm_response(response_text, message)
            
        except Exception as e:
            logger.error(f"Router classification failed: {e}")
            return RouterResponse(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                reason=f"Classification error: {str(e)}",
            )
    
    def _parse_llm_response(
        self,
        response_text: str,
        original_message: str,
    ) -> RouterResponse:
        """Parse LLM response to RouterResponse.
        
        Args:
            response_text: Raw LLM response
            original_message: Original user message for fallback
            
        Returns:
            Parsed RouterResponse
        """
        try:
            # Extract JSON from response
            json_str = self._extract_json(response_text)
            data = json.loads(json_str)
            
            classification = RouterClassification(
                intent=data.get("intent", "unknown"),
                confidence=float(data.get("confidence", 0.5)),
                keyword=data.get("keyword"),
                reason=data.get("reason"),
            )
            
            return classification.to_response()
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to parse router response: {e}")
            
            # Try heuristic classification as fallback
            return self._heuristic_classify(original_message)
    
    def _extract_json(self, text: str) -> str:
        """Extract JSON from LLM response text.
        
        Args:
            text: Raw response text
            
        Returns:
            JSON string
        """
        # Try to find JSON block
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                return text[start:end].strip()
        
        if "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                return text[start:end].strip()
        
        # Try to find raw JSON object
        if "{" in text and "}" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            return text[start:end]
        
        raise ValueError("No JSON found in response")
    
    def _heuristic_classify(self, message: str) -> RouterResponse:
        """Apply simple heuristics when LLM parsing fails.
        
        Args:
            message: User message
            
        Returns:
            Heuristic-based RouterResponse
        """
        message_lower = message.lower().strip()
        
        # Check for Japanese content (potential save intent)
        japanese_chars = sum(1 for c in message if '\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff')
        japanese_ratio = japanese_chars / max(len(message), 1)
        
        if japanese_ratio > 0.5 and len(message) > 10:
            return RouterResponse(
                intent=IntentType.SAVE,
                confidence=0.6,
                reason="Message contains significant Japanese content",
            )
        
        # Check for question patterns
        if any(q in message for q in ["?", "？", "嗎", "什麼", "怎麼", "如何"]):
            return RouterResponse(
                intent=IntentType.CHAT,
                confidence=0.5,
                reason="Message appears to be a question",
            )
        
        # Default to unknown
        return RouterResponse(
            intent=IntentType.UNKNOWN,
            confidence=0.3,
            reason="Could not determine intent",
        )
    
    async def get_chat_response(
        self,
        message: str,
        context: Optional[str] = None,
        mode: str = "balanced",
    ) -> str:
        """Generate a chat response for learning questions.

        Args:
            message: User's question
            context: Optional conversation context
            mode: LLM mode (cheap/balanced/rigorous)

        Returns:
            Generated response
        """
        system_prompt = """你是一個友善的日語學習助手。

請簡短回答用戶的日語學習相關問題。
如果問題與日語學習無關，請禮貌地引導用戶使用學習功能。

回答風格：
- 簡潔明瞭
- 舉例說明
- 鼓勵學習"""

        try:
            response = await self.llm_client.complete_with_mode(
                mode=mode,
                system_prompt=system_prompt,
                user_message=message,
                temperature=0.7,
                max_tokens=500,
            )
            
            return response.content
            
        except Exception as e:
            logger.error(f"Chat response generation failed: {e}")
            return Messages.ERROR_CHAT


# Module-level singleton
_router_service: Optional[RouterService] = None


def get_router_service() -> RouterService:
    """Get RouterService singleton."""
    global _router_service
    if _router_service is None:
        _router_service = RouterService()
    return _router_service
