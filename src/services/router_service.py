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
from src.prompts.word_explanation import (
    EN_ARTICLE_JSON_SYSTEM_PROMPT,
    EN_BATCH_JSON_SYSTEM_PROMPT,
    EN_JSON_SYSTEM_PROMPT,
    EN_PLAIN_SYSTEM_PROMPT,
    get_ja_article_json_system_prompt,
    get_ja_batch_json_system_prompt,
    get_ja_json_system_prompt,
    get_ja_plain_system_prompt,
)
from src.schemas.router import IntentType, RouterClassification, RouterResponse

logger = logging.getLogger(__name__)

# Confidence thresholds
HIGH_CONFIDENCE_THRESHOLD = 0.8
LOW_CONFIDENCE_THRESHOLD = 0.5


def _build_extracted_item(
    item_data: dict[str, Any],
    word: str,
    display: str,
    target_lang: str,
) -> dict[str, Any]:
    """將 LLM 回傳的 item 資料組裝為與 ExtractedItem schema 相容的 dict。

    Args:
        item_data: LLM 回傳的 item JSON
        word: 使用者輸入的原始單字
        display: 使用者友善的解釋文字
        target_lang: 目標語言 (ja/en)

    Returns:
        ExtractedItem 相容的 dict
    """
    extracted: dict[str, Any] = {
        "item_type": "vocab",
        "key": f"vocab:{item_data.get('surface', word)}",
        "surface": item_data.get("surface", word),
        "pos": item_data.get("pos"),
        "glossary_zh": item_data.get("glossary_zh", []),
        "example": item_data.get("example"),
        "example_translation": item_data.get("example_translation"),
        "confidence": 1.0,
        "display": display,
    }
    if target_lang == "ja":
        extracted["reading"] = item_data.get("reading")
    else:
        extracted["pronunciation"] = item_data.get("pronunciation")
    return extracted


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
                max_tokens=512,
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
        system_prompt = f"""你是一個友善的{lang_name}學習助手。回覆必須使用繁體中文（zh-TW）。

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
        system_prompt = (
            get_ja_plain_system_prompt() if target_lang == "ja"
            else EN_PLAIN_SYSTEM_PROMPT
        )

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
    ) -> tuple[str, list[dict[str, Any]], LLMTrace | None]:
        """取得單字解釋並同時回傳結構化 items 資料。

        一次 LLM 呼叫同時回傳使用者友善的解釋和結構化 ExtractedItem 欄位，
        省去後續再呼叫 ExtractorService 的步驟。

        Args:
            word: 要解釋的單字
            mode: LLM mode (cheap/balanced/rigorous)
            target_lang: 目標語言 (ja/en)

        Returns:
            (display_text, extracted_items, llm_trace | None)
            - display_text: 使用者友善的 markdown 解釋
            - extracted_items: 結構化 item 資料列表（0 個代表 LLM 無法確定詞條）
            - llm_trace: LLM 呼叫追蹤資訊（用於記錄到 api_usage_logs）
        """
        system_prompt = (
            get_ja_json_system_prompt() if target_lang == "ja"
            else EN_JSON_SYSTEM_PROMPT
        )

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

            # 新格式 "items": [...] 優先；fallback 舊格式 "item": {...}
            items_raw = response_data.get("items")
            if items_raw is None:
                old_item = response_data.get("item")
                items_raw = [old_item] if old_item and isinstance(old_item, dict) else []
            if not isinstance(items_raw, list):
                items_raw = []

            if not display:
                logger.warning("Structured word explanation returned empty display")
                return word, [], trace

            # 組裝 extracted_items list
            extracted_items: list[dict[str, Any]] = []
            for item_data in items_raw:
                if item_data and isinstance(item_data, dict):
                    extracted_items.append(
                        _build_extracted_item(item_data, word, display, target_lang)
                    )

            return display, extracted_items, trace

        except (TimeoutError, GeminiServerError):
            raise
        except Exception as e:
            logger.warning("Structured word explanation failed, falling back: %s", e)
            resp = await self.get_word_explanation(word, mode=mode, target_lang=target_lang)
            return resp.content, [], resp.to_trace()

    async def get_batch_word_explanation_structured(
        self,
        words: list[str],
        mode: str = "free",
        target_lang: str = "ja",
    ) -> tuple[list[tuple[str, str, dict[str, Any] | None]], LLMTrace | None]:
        """批次取得多個單字的解釋與結構化 item 資料（單次 LLM 呼叫）。

        Args:
            words: 要解釋的單字列表
            mode: LLM mode (free/cheap/rigorous)
            target_lang: 目標語言 (ja/en)

        Returns:
            (results, llm_trace)
            - results: list of (word, display, extracted_item_dict | None)
            - llm_trace: LLM 呼叫追蹤資訊
        """
        system_prompt = (
            get_ja_batch_json_system_prompt() if target_lang == "ja"
            else EN_BATCH_JSON_SYSTEM_PROMPT
        )
        user_message = "\n".join(words)

        try:
            response_data, trace = await self.llm_client.complete_json_with_mode(
                mode=mode,
                system_prompt=system_prompt,
                user_message=user_message,
                temperature=0.3,
                max_tokens=4096,
                total_timeout=90,
            )

            # response_data 應為 list；若 LLM 回傳 dict 包裹 array，嘗試展開
            if isinstance(response_data, dict):
                # 嘗試常見的 key：results, words, data
                for key in ("results", "words", "data"):
                    if isinstance(response_data.get(key), list):
                        response_data = response_data[key]
                        break
                else:
                    logger.warning("Batch response is dict without array key: %s", list(response_data.keys()))
                    response_data = []

            if not isinstance(response_data, list):
                logger.warning("Batch response is not a list, got %s", type(response_data))
                response_data = []

            # 建立 word → entry 對照表
            entry_map: dict[str, dict[str, Any]] = {}
            for entry in response_data:
                if isinstance(entry, dict) and "word" in entry:
                    entry_map[entry["word"].strip().lower()] = entry

            results: list[tuple[str, str, dict[str, Any] | None]] = []
            for word in words:
                entry = entry_map.get(word.strip().lower())
                if entry and entry.get("display"):
                    display = entry["display"]
                    item_data = entry.get("item")
                    extracted_item: dict[str, Any] | None = None
                    if item_data and isinstance(item_data, dict):
                        extracted_item = _build_extracted_item(
                            item_data, word, display, target_lang
                        )
                    results.append((word, display, extracted_item))
                else:
                    # LLM 未回傳此字的結果
                    results.append((word, "", None))

            return results, trace

        except (TimeoutError, GeminiServerError):
            raise
        except Exception as e:
            logger.warning("Batch word explanation failed: %s", e)
            # 全部標記為失敗，讓呼叫端走 fallback
            return [(w, "", None) for w in words], None

    async def get_word_explanation_with_context(
        self,
        word: str,
        article_context: str,
        mode: str = "free",
        target_lang: str = "ja",
    ) -> tuple[str, list[dict[str, Any]], LLMTrace | None]:
        """帶文章語境的單字查詞（文章閱讀模式使用）。

        複用共用的核心規則 prompt，在 system prompt 中注入文章語境。

        Args:
            word: 要解釋的單字（日文或中文皆可）
            article_context: 使用者正在閱讀的文章原文
            mode: LLM mode (cheap/balanced/rigorous)
            target_lang: 目標語言 (ja/en)

        Returns:
            (display_text, extracted_items, llm_trace | None)
        """
        from src.prompts.article import build_article_word_lookup_system_prompt

        base_prompt = (
            get_ja_article_json_system_prompt() if target_lang == "ja"
            else EN_ARTICLE_JSON_SYSTEM_PROMPT
        )
        system_prompt = build_article_word_lookup_system_prompt(
            base_prompt, article_context
        )

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

            # 新格式 "items": [...] 優先；fallback 舊格式 "item": {...}
            items_raw = response_data.get("items")
            if items_raw is None:
                old_item = response_data.get("item")
                items_raw = [old_item] if old_item and isinstance(old_item, dict) else []
            if not isinstance(items_raw, list):
                items_raw = []

            if not display:
                logger.warning("Article word lookup returned empty display")
                return word, [], trace

            # 組裝 extracted_items list
            extracted_items: list[dict[str, Any]] = []
            for item_data in items_raw:
                if item_data and isinstance(item_data, dict):
                    extracted_items.append(
                        _build_extracted_item(item_data, word, display, target_lang)
                    )

            return display, extracted_items, trace

        except (TimeoutError, GeminiServerError):
            raise
        except Exception as e:
            logger.warning("Article word lookup failed, falling back to context-free: %s", e)
            resp = await self.get_word_explanation(word, mode=mode, target_lang=target_lang)
            fallback_note = "\n\n⚠️ 語境查詞暫時不可用，以上為一般解釋。"
            return resp.content + fallback_note, [], resp.to_trace()


# 模組層級 singleton
_router_service: RouterService | None = None


def get_router_service() -> RouterService:
    """Get RouterService singleton."""
    global _router_service
    if _router_service is None:
        _router_service = RouterService()
    return _router_service
