"""
Router service for LLM-based intent classification.

T082: Implement RouterService in src/services/router_service.py
DoD: classify(message) 回傳 RouterResponse；confidence < 0.5 觸發 fallback
"""

from __future__ import annotations

import json
import logging
from typing import Any

from google.genai.errors import ServerError as GeminiServerError
from pydantic import ValidationError

from src.lib.llm_client import LLMResponse, LLMTrace, get_llm_client
from src.prompts.router import format_router_request, get_system_prompt
from src.schemas.router import IntentType, RouterClassification, RouterResponse

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

        .. deprecated::
            已被 webhook.py 的 _classify_input() 結構特徵分類取代。
            保留此方法以維持單元測試相容性，生產程式碼不再呼叫。

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
            logger.error("Router classification failed, using heuristic: %s", e)
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
            logger.warning("Failed to parse router response: %s", e)
            
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
        """依規則啟發式分類使用者意圖（LLM 解析失敗時的 fallback）。

        .. deprecated::
            已被 webhook.py 的 _classify_input() 結構特徵分類取代。
            保留此方法以維持單元測試相容性。
        """
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
            max_tokens=1024,
            total_timeout=60,
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
            system_prompt = """你是一個專業的日語老師。請用繁體中文解釋這個日文單字，格式如下：

📖 單字（讀音，如有漢字）
詞性 ・ 簡短類別說明

意思（1-2句話）

📝 例句
[日文例句]
（中文翻譯）

保持簡潔，不要太冗長。若詞彙有重要用法陷阱可加一行說明。"""
        else:
            system_prompt = """你是一個專業的英語老師。請用繁體中文解釋這個英文單字，格式如下：

📖 單字 /音標/
詞性

意思（1-2句話）

📝 例句
[英文例句]
（中文翻譯）

💡 用法提示（若該字有常見用法陷阱或搭配詞則加上，否則省略）

保持簡潔，不要太冗長。"""

        try:
            response = await self.llm_client.complete_with_mode(
                mode=mode,
                system_prompt=system_prompt,
                user_message=word,
                temperature=0.3,
                max_tokens=1024,
                total_timeout=60,
            )

            return response

        except Exception as e:
            logger.error("Word explanation generation failed: %s", e)
            raise

    async def get_word_explanation_structured(
        self,
        word: str,
        mode: str = "free",
        target_lang: str = "ja",
    ) -> tuple[str, dict[str, Any] | None, LLMTrace | None]:
        """取得單字解釋並同時回傳結構化 item 資料。

        一次 LLM 呼叫同時回傳使用者友善的解釋和結構化 ExtractedItem 欄位，
        省去後續再呼叫 ExtractorService 的步驟。

        Args:
            word: 要解釋的單字
            mode: LLM mode (cheap/balanced/rigorous)
            target_lang: 目標語言 (ja/en)

        Returns:
            (display_text, extracted_item_dict | None, llm_trace | None)
            - display_text: 使用者友善的 markdown 解釋
            - extracted_item_dict: 結構化 item 資料（JSON parse 失敗時為 None）
            - llm_trace: LLM 呼叫追蹤資訊（用於記錄到 api_usage_logs）
        """
        if target_lang == "ja":
            system_prompt = """你是一個專業的日語老師。請用 JSON 格式回傳以下兩個欄位：

1. "display": 用繁體中文解釋這個日文單字，格式如下：
📖 單字（讀音，如有漢字）
詞性 ・ 簡短類別說明

意思（1-2句話）

📝 例句
[日文例句]
（中文翻譯）

保持簡潔，不要太冗長。若詞彙有重要用法陷阱可加一行說明。

2. "item": 結構化資料，包含以下欄位：
- "surface": 單字表記形（如「考える」）
- "reading": 假名讀音（如「かんがえる」）
- "pos": 詞性（如 "verb", "noun", "i-adjective"）
- "glossary_zh": 繁體中文釋義列表（如 ["思考", "考慮"]）
- "example": 日文例句
- "example_translation": 例句的繁體中文翻譯

回覆必須是合法 JSON。"""
        else:
            system_prompt = """你是一個專業的英語老師。請用 JSON 格式回傳以下兩個欄位：

1. "display": 用繁體中文解釋這個英文單字，格式如下：
📖 單字 /音標/
詞性

意思（1-2句話）

📝 例句
[英文例句]
（中文翻譯）

💡 用法提示（若該字有常見用法陷阱或搭配詞則加上，否則省略）

保持簡潔，不要太冗長。

2. "item": 結構化資料，包含以下欄位：
- "surface": 單字（如 "consider"）
- "pronunciation": 音標（如 "/kənˈsɪdər/"）
- "pos": 詞性（如 "verb", "noun", "adjective"）
- "glossary_zh": 繁體中文釋義列表（如 ["考慮", "認為"]）
- "example": 英文例句
- "example_translation": 例句的繁體中文翻譯

回覆必須是合法 JSON。"""

        try:
            response_data, trace = await self.llm_client.complete_json_with_mode(
                mode=mode,
                system_prompt=system_prompt,
                user_message=word,
                temperature=0.3,
                max_tokens=2048,
                total_timeout=60,
            )

            display = response_data.get("display", "")
            item_data = response_data.get("item")

            if not display:
                # JSON 成功但 display 為空，不應發生但做防禦
                logger.warning("Structured word explanation returned empty display")
                return word, item_data, trace

            # 組裝 extracted_item_dict（與 ExtractedItem schema 相容）
            extracted_item: dict[str, Any] | None = None
            if item_data and isinstance(item_data, dict):
                extracted_item = {
                    "item_type": "vocab",
                    "key": f"vocab:{item_data.get('surface', word)}",
                    "surface": item_data.get("surface", word),
                    "pos": item_data.get("pos"),
                    "glossary_zh": item_data.get("glossary_zh", []),
                    "example": item_data.get("example"),
                    "example_translation": item_data.get("example_translation"),
                    "confidence": 1.0,
                }
                if target_lang == "ja":
                    extracted_item["reading"] = item_data.get("reading")
                else:
                    extracted_item["pronunciation"] = item_data.get("pronunciation")

            return display, extracted_item, trace

        except (TimeoutError, GeminiServerError):
            # Server 不可用或 timeout — 同一 provider 再呼叫也會失敗，直接傳播
            raise
        except Exception as e:
            logger.warning("Structured word explanation failed, falling back: %s", e)
            # Fallback：呼叫原版 get_word_explanation（僅 JSON 解析等客戶端錯誤時）
            resp = await self.get_word_explanation(word, mode=mode, target_lang=target_lang)
            return resp.content, None, resp.to_trace()


# 模組層級 singleton
_router_service: RouterService | None = None


def get_router_service() -> RouterService:
    """Get RouterService singleton."""
    global _router_service
    if _router_service is None:
        _router_service = RouterService()
    return _router_service
