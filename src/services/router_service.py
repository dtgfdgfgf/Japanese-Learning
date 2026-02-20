"""
Router service for LLM-based intent classification.

T082: Implement RouterService in src/services/router_service.py
DoD: classify(message) 回傳 RouterResponse；confidence < 0.5 觸發 fallback
"""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from src.lib.llm_client import LLMResponse, get_llm_client
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
        context: str | None = None,
        mode: str = "free",
        target_lang: str = "ja",
    ) -> tuple[RouterResponse, LLMResponse | None]:
        """Classify user message intent.

        Args:
            message: User's message
            context: Optional conversation context
            mode: LLM mode (cheap/balanced/rigorous)
            target_lang: 目標語言 (ja/en)

        Returns:
            (RouterResponse, LLMResponse | None) — LLM 失敗時第二元素為 None
        """
        try:
            user_prompt = format_router_request(message, context)
            system_prompt = get_system_prompt(lang=target_lang)

            llm_response = await self.llm_client.complete_with_mode(
                mode=mode,
                system_prompt=system_prompt,
                user_message=user_prompt,
                temperature=0.3,
            )
            response_text = llm_response.content

            # 解析回應
            parsed = self._parse_llm_response(response_text, message, target_lang=target_lang)
            return parsed, llm_response

        except Exception as e:
            logger.error(f"Router classification failed, using heuristic: {e}")
            return self._heuristic_classify(message, target_lang=target_lang), None
    
    def _parse_llm_response(
        self,
        response_text: str,
        original_message: str,
        target_lang: str = "ja",
    ) -> RouterResponse:
        """Parse LLM response to RouterResponse.

        Args:
            response_text: Raw LLM response
            original_message: Original user message for fallback
            target_lang: 目標語言 (ja/en)

        Returns:
            Parsed RouterResponse
        """
        try:
            # 從 LLM 回應中提取 JSON
            json_str = self._extract_json(response_text)
            data = json.loads(json_str)
            
            classification = RouterClassification(
                intent=data.get("intent", "unknown"),
                confidence=float(data.get("confidence", 0.5)),
                keyword=data.get("keyword"),
                reason=data.get("reason"),
            )
            
            return classification.to_response()
            
        except (json.JSONDecodeError, KeyError, ValueError, ValidationError) as e:
            logger.warning(f"Failed to parse router response: {e}")
            
            # JSON 解析失敗，使用啟發式分類
            return self._heuristic_classify(original_message, target_lang=target_lang)
    
    def _extract_json(self, text: str) -> str:
        """Extract JSON from LLM response text.
        
        Args:
            text: Raw response text
            
        Returns:
            JSON string
        """
        # 嘗試從 code block 提取 JSON
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
        
        # 尋找第一個完整的 JSON 物件（配對大括號）
        if "{" in text:
            start = text.find("{")
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1]
        
        raise ValueError("No JSON found in response")
    
    def _heuristic_classify(self, message: str, target_lang: str = "ja") -> RouterResponse:
        """依規則啟發式分類使用者意圖（LLM 解析失敗時的 fallback）。"""
        stripped = message.strip()
        is_single_token = len(stripped.split()) == 1

        # 字元統計
        kana_chars = sum(
            1 for c in message
            if '\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff' or '\uff65' <= c <= '\uff9f'
        )
        cjk_chars = sum(1 for c in message if '\u4e00' <= c <= '\u9fff')
        japanese_chars = kana_chars + cjk_chars
        ascii_alpha_chars = sum(1 for c in message if c.isascii() and c.isalpha())
        total_chars = max(len(message.replace(" ", "")), 1)

        japanese_ratio = japanese_chars / total_chars
        english_ratio = ascii_alpha_chars / total_chars

        # 問句優先判斷
        has_question = any(q in message for q in ["?", "？", "嗎", "什麼", "怎麼", "如何"])

        # --- 短單字偵測（含跨語言備援） ---
        if not has_question and is_single_token:
            # 英文短單字：目標語言為英文時最短 1 字元，跨語言時最短 3 字元
            en_min_len = 1 if target_lang == "en" else 3
            if english_ratio > 0.8 and en_min_len <= len(stripped) <= 30:
                return RouterResponse(
                    intent=IntentType.SAVE,
                    confidence=0.85,
                    reason="Single English word detected (heuristic)",
                )

            # 日文短詞：有假名 → 高信心度；純漢字 → 可能是中文，降低信心度
            if japanese_ratio >= 0.5 and len(stripped) <= 15:
                conf = 0.85 if kana_chars > 0 else 0.7
                reason = (
                    "Short Japanese word/phrase detected (heuristic)"
                    if kana_chars > 0
                    else "Short CJK text, possibly Chinese (heuristic)"
                )
                return RouterResponse(
                    intent=IntentType.SAVE,
                    confidence=conf,
                    reason=reason,
                )

        # --- 長文偵測 ---
        # 日文模式：多數日文字元 → save
        if target_lang == "ja" and japanese_ratio > 0.5 and len(message) > 10:
            return RouterResponse(
                intent=IntentType.SAVE,
                confidence=0.6,
                reason="Message contains significant Japanese content",
            )

        # 英文模式：多數英文字元且夠長 → save
        if target_lang == "en" and english_ratio > 0.5 and len(message) > 20:
            return RouterResponse(
                intent=IntentType.SAVE,
                confidence=0.6,
                reason="Message contains significant English content",
            )

        # 問句 → chat
        if has_question:
            return RouterResponse(
                intent=IntentType.CHAT,
                confidence=0.5,
                reason="Message appears to be a question",
            )

        # 無法判斷
        return RouterResponse(
            intent=IntentType.UNKNOWN,
            confidence=0.3,
            reason="Could not determine intent",
        )
    
    async def get_chat_response(
        self,
        message: str,
        context: str | None = None,
        mode: str = "free",
        target_lang: str = "ja",
    ) -> LLMResponse:
        """Generate a chat response for learning questions.

        Args:
            message: User's question
            context: Optional conversation context
            mode: LLM mode (cheap/balanced/rigorous)
            target_lang: 目標語言 (ja/en)

        Returns:
            LLMResponse（失敗時 raise，由呼叫端 try/except 處理）
        """
        lang_name = {"ja": "日語", "en": "英語"}.get(target_lang, "日語")
        system_prompt = f"""你是一個友善的{lang_name}學習助手。

請簡短回答用戶的{lang_name}學習相關問題。
如果問題與{lang_name}學習無關，請禮貌地引導用戶使用學習功能。

回答風格：
- 簡潔明瞭
- 舉例說明
- 鼓勵學習"""

        response = await self.llm_client.complete_with_mode(
            mode=mode,
            system_prompt=system_prompt,
            user_message=message,
            temperature=0.7,
        )

        return response

    async def get_word_explanation(
        self,
        word: str,
        mode: str = "free",
        target_lang: str = "ja",
    ) -> LLMResponse:
        """取得單字解釋。

        Args:
            word: 要解釋的單字
            mode: LLM mode (cheap/balanced/rigorous)
            target_lang: 目標語言 (ja/en)

        Returns:
            LLMResponse（失敗時 raise，由呼叫端 try/except 處理）
        """
        if target_lang == "ja":
            system_prompt = """你是一個專業的日語老師。請用繁體中文簡短解釋這個日文單字的意思。

格式要求：
- 先標注讀音（如有漢字）
- 簡短解釋意思（1-2句話）
- 如有常見用法可以簡單提及

保持簡潔，不要太冗長。"""
        else:
            system_prompt = """你是一個專業的英語老師。請用繁體中文簡短解釋這個英文單字的意思。

格式要求：
- 標注發音（音標）
- 簡短解釋意思（1-2句話）
- 如有常見用法可以簡單提及

保持簡潔，不要太冗長。"""

        try:
            response = await self.llm_client.complete_with_mode(
                mode=mode,
                system_prompt=system_prompt,
                user_message=word,
                temperature=0.3,
            )

            return response

        except Exception as e:
            logger.error(f"Word explanation generation failed: {e}")
            raise


# 模組層級 singleton
_router_service: RouterService | None = None


def get_router_service() -> RouterService:
    """Get RouterService singleton."""
    global _router_service
    if _router_service is None:
        _router_service = RouterService()
    return _router_service
