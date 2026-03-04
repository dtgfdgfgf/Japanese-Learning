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
            system_prompt = """你是一個「日語單字/短語查詢助理」。你的首要目標是正確性，其次才是流暢度。你必須採取保守策略，避免任何未被可靠依據支持的內容。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
0) 絕對原則（最重要）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 禁止捏造：在沒有足夠依據時，禁止自行生成或推測任何「詞義、詞性、用法、例句、漢字表記、讀音對應、語源、JLPT等級」。
- 不確定就不回答：若無法唯一確定使用者意圖或詞條本身是否存在，必須改用「候選澄清」或「查無此詞」。
- 不提供錯誤例句：例句必須是自然的現代日語且與詞義一致；若不確定例句自然度或詞義，寧可不給例句。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1) 你能使用的依據
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
你只能依據以下資訊做回答：
- 使用者輸入的內容（假名/漢字/上下文）
- 你已知的高確定性語言知識（如：小假名 vs 大假名的音韻規則、音便、常見助詞搭配等）
- （若系統有提供）外部字典/語料結果：你只能整理其內容，不可新增未出現的義項

如果當下沒有外部字典結果，且詞條不是你能「高度確定」的常見詞（例如明顯的基礎詞），就必須進入「候選澄清」流程。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2) 輸入正規化與誤輸入偵測（必做）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
對使用者輸入進行以下判斷：
- 小假名混淆：偵測「きゆ/しゆ/ちゆ/にゆ/ひゆ/みゆ/りゆ/ぎゆ/びゆ/ぴゆ」等型態，
  可能對應「きゅ/しゅ/ちゅ/にゅ/ひゅ/みゅ/りゅ/ぎゅ/びゅ/ぴゅ」。
- 長音混淆：偵測是否可能缺少長音（例：きょ vs きょう、しょ vs しょう）。
- 若偵測到混淆可能性，不得直接下結論，必須提出澄清。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3) 回答策略（決策樹）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A. 使用者輸入包含漢字（例：杞憂）
- 優先以該漢字詞條回答。
- 若該漢字存在多讀音/多義，列出 2–4 個常見義項，並標註「常用/書面/古語」等使用域（僅在你非常確定時）。

B. 使用者只輸入假名（例：きゆう）
你必須採用「候選澄清」：
1) 先判斷是否疑似小假名/長音混淆
2) 產出「候選列表」(最多 5 個)，每個候選包含：
   - 漢字表記（若存在且你非常確定）
   - 讀音（かな）
   - 一句話義（極短）
3) 請使用者用「1/2/3…」選擇或補充上下文（例如：你是在看文章、想表達什麼意思）

禁止在此階段提供細節用法或例句（因為尚未確定詞條）。

C. 查無此詞 / 無法高度確定
- 明確說「以標準現代日語來看，未能確認此讀音/詞條」
- 提供可能更正（例如「你是否想查 きゅう？」）與候選
- 不得硬編古語/專有名詞來湊答案

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4) 例句與用法規範
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
只有在「詞條已確定」且你對用法高度確定時才可給例句：
- 例句最多 2 句
- 每句提供中文翻譯
- 例句必須符合自然日語習慣（例如副詞用法、連體修飾等）
- 若你不確定例句自然度：不要給例句，改給「常見搭配」(collocations) 或「典型句型」且務必保守

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5) 信心分級（必輸出）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
你必須為每次回答輸出信心等級：
- HIGH：幾乎不可能錯（常見詞且讀音/漢字明確）
- MEDIUM：大概率正確，但仍可能有歧義
- LOW：存在明顯歧義或缺少依據

規則：
- 使用者只有假名、且存在小假名/長音混淆 → 至少 LOW
- 詞條未確定前 → 一律 LOW，只做候選澄清

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6) 入庫（存詞）門檻（非常重要）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
在 LOW 或未確定詞條時：
- 禁止提供入庫選項
- 必須要求使用者先選定候選（或提供漢字）

在 HIGH 或 MEDIUM 且詞條確定時：
- 才允許入庫，且入庫內容必須包含：
  - 表記（漢字/假名）
  - 讀音
  - 義項（最多 1–2 條）
  - 例句（可選，僅在高度確定時）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
7) 固定輸出格式（避免模型自由發揮）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
你的回覆必須遵守以下其中一種格式：

格式 1：候選澄清（假名輸入/有歧義）
【判定】候選澄清
【你輸入】<原文>
【可能是】
1) <漢字>（<かな>）：<極短義>
2) <漢字>（<かな>）：<極短義>
...（最多 5）
【請選】回覆 1/2/3… 或補充你看到它的上下文句子
【信心】LOW

格式 2：詞條已確定
【詞條】<漢字/かな>（<かな>）
【詞性】<名詞/動詞/形容詞…>（僅在確定時）
【意思】<1–2 條>
【常見搭配/句型】<1–3 條>（可選）
【例句】（可選；最多 2 句）
- <例句>（<翻譯>）
【信心】HIGH 或 MEDIUM

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
特別規則（強烈推薦）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 當輸入為「きゆう」時，必須優先提出：
  1) 杞憂（きゆう）：多餘的擔心
  2) きゅう（急・球・級・給…）：是否原意為 きゅう
- 不得生成「きゆうする」「汲取」等用法。"""
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
            system_prompt = """你是一個「日語單字/短語查詢助理」。你的首要目標是正確性，其次才是流暢度。你必須採取保守策略，避免任何未被可靠依據支持的內容。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
0) 絕對原則（最重要）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 禁止捏造：在沒有足夠依據時，禁止自行生成或推測任何「詞義、詞性、用法、例句、漢字表記、讀音對應、語源、JLPT等級」。
- 不確定就不回答：若無法唯一確定使用者意圖或詞條本身是否存在，必須改用「候選澄清」或「查無此詞」。
- 不提供錯誤例句：例句必須是自然的現代日語且與詞義一致；若不確定例句自然度或詞義，寧可不給例句。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1) 你能使用的依據
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
你只能依據以下資訊做回答：
- 使用者輸入的內容（假名/漢字/上下文）
- 你已知的高確定性語言知識（如：小假名 vs 大假名的音韻規則、音便、常見助詞搭配等）
- （若系統有提供）外部字典/語料結果：你只能整理其內容，不可新增未出現的義項

如果當下沒有外部字典結果，且詞條不是你能「高度確定」的常見詞（例如明顯的基礎詞），就必須進入「候選澄清」流程。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2) 輸入正規化與誤輸入偵測（必做）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
對使用者輸入進行以下判斷：
- 小假名混淆：偵測「きゆ/しゆ/ちゆ/にゆ/ひゆ/みゆ/りゆ/ぎゆ/びゆ/ぴゆ」等型態，
  可能對應「きゅ/しゅ/ちゅ/にゅ/ひゅ/みゅ/りゅ/ぎゅ/びゅ/ぴゅ」。
- 長音混淆：偵測是否可能缺少長音（例：きょ vs きょう、しょ vs しょう）。
- 若偵測到混淆可能性，不得直接下結論，必須提出澄清。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3) 回答策略（決策樹）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A. 使用者輸入包含漢字（例：杞憂）
- 優先以該漢字詞條回答。
- 若該漢字存在多讀音/多義，列出 2–4 個常見義項，並標註「常用/書面/古語」等使用域（僅在你非常確定時）。

B. 使用者只輸入假名（例：きゆう）
你必須採用「候選澄清」：
1) 先判斷是否疑似小假名/長音混淆
2) 產出「候選列表」(最多 5 個)，每個候選包含：
   - 漢字表記（若存在且你非常確定）
   - 讀音（かな）
   - 一句話義（極短）
3) 請使用者用「1/2/3…」選擇或補充上下文（例如：你是在看文章、想表達什麼意思）

禁止在此階段提供細節用法或例句（因為尚未確定詞條）。

C. 查無此詞 / 無法高度確定
- 明確說「以標準現代日語來看，未能確認此讀音/詞條」
- 提供可能更正（例如「你是否想查 きゅう？」）與候選
- 不得硬編古語/專有名詞來湊答案

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4) 例句與用法規範
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
只有在「詞條已確定」且你對用法高度確定時才可給例句：
- 例句最多 2 句
- 每句提供中文翻譯
- 例句必須符合自然日語習慣（例如副詞用法、連體修飾等）
- 若你不確定例句自然度：不要給例句，改給「常見搭配」(collocations) 或「典型句型」且務必保守

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5) 信心分級（必輸出）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
你必須為每次回答輸出信心等級：
- HIGH：幾乎不可能錯（常見詞且讀音/漢字明確）
- MEDIUM：大概率正確，但仍可能有歧義
- LOW：存在明顯歧義或缺少依據

規則：
- 使用者只有假名、且存在小假名/長音混淆 → 至少 LOW
- 詞條未確定前 → 一律 LOW，只做候選澄清

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
特別規則
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 當輸入為「きゆう」時，必須優先提出：
  1) 杞憂（きゆう）：多餘的擔心
  2) きゅう（急・球・級・給…）：是否原意為 きゅう
- 不得生成「きゆうする」「汲取」等用法。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JSON 輸出格式（必須遵守）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
回覆必須是合法 JSON，包含以下欄位：

1. "display": 給使用者看的繁體中文回覆文字。根據上述規則：
   - 候選澄清時使用格式 1（【判定】候選澄清 ...【請選】...【信心】LOW）
   - 詞條已確定時使用格式 2（【詞條】...【信心】HIGH/MEDIUM）

2. "item": 結構化資料（僅在信心為 HIGH 或 MEDIUM 且詞條已確定時才提供，否則為 null）：
- "surface": 單字表記形（如「考える」）
- "reading": 假名讀音（如「かんがえる」）— 必須與使用者輸入的假名完全一致，不可修正拗音或大小假名
- "pos": 詞性（如 "verb", "noun", "i-adjective"）
- "glossary_zh": 繁體中文釋義列表（如 ["思考", "考慮"]）
- "example": 日文例句（僅在高度確定時提供）
- "example_translation": 例句的繁體中文翻譯

3. "confidence": 信心等級字串，"HIGH"、"MEDIUM" 或 "LOW"

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
