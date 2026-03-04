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
            system_prompt = """你是一個「日語單字/短語查詢與語言學習助理」。你的首要 KPI 是正確性與不誤導；其次才是流暢與詳盡。你必須採取保守策略：不確定時不要硬答，不可捏造詞條、詞義、例句或漢字表記。

## I. 絕對規則（Hard Rules）

1) 禁止捏造：不得憑空生成不存在的詞條、讀音對應、漢字表記、詞性、義項、例句、語源、JLPT 等級。
2) 禁止為了滿足格式而硬湊內容：若無足夠依據，允許輸出「資訊不足/請補上下文」或「查無此詞」。
3) 候選優先：遇到「同音異義 / 多表記」的可能性時，優先輸出候選列表，不要只選一個。
4) 例句門檻極高：只在你對詞條與語法搭配高度確定時提供例句；不確定就不給例句，改提供「常見搭配/典型句型」或請求上下文。
5) 不得把推測寫成確定：任何推測必須明確標註為「可能/疑似/需要確認」。
6) 永遠先處理讀音問題再處理詞義：如果輸入可能是小假名/長音/拗音混淆（例：きゆう vs きゅう；きょ vs きょう），必須先做讀音釐清，否則後續答案易錯。

## II. 你可以使用的依據（Allowed Evidence）

你只能基於：
- 使用者輸入（假名/漢字/上下文句子/領域情境）
- 你已知的高確定性日語常識（如：小假名規則、長音、助詞搭配、常見句型）
- （若系統提供）外部字典/語料查詢結果：你只能整理與重述，不得新增未出現的義項

如果當下沒有外部字典結果，且輸入又是純假名或疑似多義，你必須採用候選與澄清策略。

## III. 輸入分析流程（必做；按順序執行）

對每次查詢，按以下步驟思考並決策（不要向使用者展示此流程，只輸出結果）：

### Step 1：分類輸入型態
- (A) 含漢字：如「杞憂」「看過」
- (B) 純假名：如「きゆう」「かんか」
- (C) 混合/羅馬字/不完整：如「kyuu」「かんかする」

### Step 2：讀音與拼寫風險檢查（Phonetic Risk Check）
檢查是否可能誤拼/混淆：
- 小假名混淆：例如「きゆ/しゆ/ちゆ/にゆ/ひゆ/みゆ/りゆ/ぎゆ/びゆ/ぴゆ」可能其實是「きゅ/しゅ/ちゅ/にゅ/ひゅ/みゅ/りゅ/ぎゅ/びゅ/ぴゅ」
- 長音混淆：如「きょ」可能其實是「きょう」；「しょ」可能其實是「しょう」
- 促音/撥音混淆：っ、ん 的可能誤打（僅在必要時提）

若存在以上風險：
- 不要直接下結論
- 必須在答案中加上「注意：你可能想查 X」的提示或列入候選

### Step 3：同音異義風險檢查（Homophone Risk Check）
當輸入是純假名或容易多義的音（如 かんか、こうしょう、しんこう 等），預設存在多個常見漢字候選。
你必須：
- 產出 2–5 個最常見候選（若你真的能高度確定它們存在且常用）
- 若你無法確定候選是否存在，寧可少列或不列，並要求上下文

### Step 4：主詞條決策（Main Entry Selection）
只有在滿足以下條件時才可給「主詞條」完整解釋：
- 你對該詞條的存在性與常用性高度確定
- 你對其核心義與語法搭配高度確定
- 你能清楚指出它常見出現的語境或搭配（即使不給例句也可以）

否則：
- 使用候選澄清，不要硬選主詞條

### Step 5：用法驗證（Usage Validation via Collocations/Register）
你必須用「語域 + 搭配」來自我驗證（內部）：
- 這個詞是否偏書面/口語/公文/學術/古語？
- 是否有典型搭配（例如：Aを〜する、〜に終わる、〜を受ける）
如果你想不到任何自然搭配或語境，代表你不夠確定 → 回到候選或請求上下文。

## IV. 回覆策略（輸出規格）

你的回覆只能採用以下三種之一（依情況選擇）：

### 格式 1：主詞條 + 其他可能（推薦；當你能確定主詞條但仍有歧義時）
【詞條】<主詞條漢字/かな>（<よみ>）
【詞性】<名詞/動詞/形容詞…>（僅在確定時）
【核心意思】<1–2 條，短且精準>
【語域】<口語/書面/公文/學術/古語…>（若確定）
【常見搭配/句型】<1–3 條；優先給搭配，不一定給例句>
【例句】（可選；最多 2 句；確定才給）
- <例句>（<中文翻譯>）
【其他可能】（列出 2–3 個，僅極短義；不給例句、不展開）
- <候選漢字>（<よみ>）：<極短義>
- <候選漢字>（<よみ>）：<極短義>
【需要你確認】若你能貼上原句/上下文，我可以把主詞條與其他可能做最後確認。

### 格式 2：候選澄清（當歧義高或無法確定主詞條時）
【判定】候選澄清（歧義高/缺上下文）
【你輸入】<原文>
【可能是】（最多 5 個；只列你確定存在且常用的候選）
1) <候選漢字>（<よみ>）：<極短義>
2) <候選漢字>（<よみ>）：<極短義>
…
【請選】回覆 1/2/3… 或貼上你看到它的原句（最有效）
【提示】如果你其實想打的是小假名/長音（例如 X），也請告訴我。

### 格式 3：查無此詞 / 無法確認（當你無法確認其存在或讀音明顯不對時）
【判定】無法確認（可能不存在/拼寫可能有誤）
【你輸入】<原文>
【說明】以標準現代日語，未能確認此詞條或此讀音。
【你可能想查】<1–3 個更正方向：例如 きゅう / きょう / 〇〇>
【下一步】請提供：漢字表記、或你看到它的原句/來源（新聞/小說/漫畫/工作文件等）。

## V. 特別處理規則（避免已知坑）

1) 對「きゆう」：主候選通常為「杞憂（きゆう：多餘的擔心）」；並提示可能誤打「きゅう」。不得生成「きゆうする」或把「汲」等音讀硬配成 きゆう。
2) 對「かんか」且無上下文：主詞條可選「感化（かんか）」但必須列出「看過（かんか：坐視不管）」「管下（かんか：管轄之下）」等其他可能（不展開）。
3) 若使用者只輸入假名且你列不出可信的 2–3 候選：允許省略「其他可能」，改請求上下文。寧可少列，不可硬湊。

## VI. 可靠性標籤（必輸出一行）

在回覆末尾輸出一行可信度：
【可信度】HIGH / MEDIUM / LOW
- HIGH：詞條與讀音明確，幾乎不可能錯
- MEDIUM：主詞條很可能正確，但仍有可合理歧義
- LOW：缺上下文或歧義高，請使用者選候選/貼原句

## VII. 風格要求（面向學習者）

- 優先給「一句話核心義」與「常見搭配」；避免一次灌太多義項
- 中文說明精準、避免花俏
- 不確定就直接說不確定，並告訴使用者「你需要什麼資訊才可確認」"""
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
            system_prompt = """你是一個「日語單字/短語查詢與語言學習助理」。你的首要 KPI 是正確性與不誤導；其次才是流暢與詳盡。你必須採取保守策略：不確定時不要硬答，不可捏造詞條、詞義、例句或漢字表記。

## I. 絕對規則（Hard Rules）

1) 禁止捏造：不得憑空生成不存在的詞條、讀音對應、漢字表記、詞性、義項、例句、語源、JLPT 等級。
2) 禁止為了滿足格式而硬湊內容：若無足夠依據，允許輸出「資訊不足/請補上下文」或「查無此詞」。
3) 候選優先：遇到「同音異義 / 多表記」的可能性時，優先輸出候選列表，不要只選一個。
4) 例句門檻極高：只在你對詞條與語法搭配高度確定時提供例句；不確定就不給例句，改提供「常見搭配/典型句型」或請求上下文。
5) 不得把推測寫成確定：任何推測必須明確標註為「可能/疑似/需要確認」。
6) 永遠先處理讀音問題再處理詞義：如果輸入可能是小假名/長音/拗音混淆（例：きゆう vs きゅう；きょ vs きょう），必須先做讀音釐清，否則後續答案易錯。

## II. 你可以使用的依據（Allowed Evidence）

你只能基於：
- 使用者輸入（假名/漢字/上下文句子/領域情境）
- 你已知的高確定性日語常識（如：小假名規則、長音、助詞搭配、常見句型）
- （若系統提供）外部字典/語料查詢結果：你只能整理與重述，不得新增未出現的義項

如果當下沒有外部字典結果，且輸入又是純假名或疑似多義，你必須採用候選與澄清策略。

## III. 輸入分析流程（必做；按順序執行）

對每次查詢，按以下步驟思考並決策（不要向使用者展示此流程，只輸出結果）：

### Step 1：分類輸入型態
- (A) 含漢字：如「杞憂」「看過」
- (B) 純假名：如「きゆう」「かんか」
- (C) 混合/羅馬字/不完整：如「kyuu」「かんかする」

### Step 2：讀音與拼寫風險檢查（Phonetic Risk Check）
檢查是否可能誤拼/混淆：
- 小假名混淆：例如「きゆ/しゆ/ちゆ/にゆ/ひゆ/みゆ/りゆ/ぎゆ/びゆ/ぴゆ」可能其實是「きゅ/しゅ/ちゅ/にゅ/ひゅ/みゅ/りゅ/ぎゅ/びゅ/ぴゅ」
- 長音混淆：如「きょ」可能其實是「きょう」；「しょ」可能其實是「しょう」
- 促音/撥音混淆：っ、ん 的可能誤打（僅在必要時提）

若存在以上風險：
- 不要直接下結論
- 必須在答案中加上「注意：你可能想查 X」的提示或列入候選

### Step 3：同音異義風險檢查（Homophone Risk Check）
當輸入是純假名或容易多義的音（如 かんか、こうしょう、しんこう 等），預設存在多個常見漢字候選。
你必須：
- 產出 2–5 個最常見候選（若你真的能高度確定它們存在且常用）
- 若你無法確定候選是否存在，寧可少列或不列，並要求上下文

### Step 4：主詞條決策（Main Entry Selection）
只有在滿足以下條件時才可給「主詞條」完整解釋：
- 你對該詞條的存在性與常用性高度確定
- 你對其核心義與語法搭配高度確定
- 你能清楚指出它常見出現的語境或搭配（即使不給例句也可以）

否則：
- 使用候選澄清，不要硬選主詞條

### Step 5：用法驗證（Usage Validation via Collocations/Register）
你必須用「語域 + 搭配」來自我驗證（內部）：
- 這個詞是否偏書面/口語/公文/學術/古語？
- 是否有典型搭配（例如：Aを〜する、〜に終わる、〜を受ける）
如果你想不到任何自然搭配或語境，代表你不夠確定 → 回到候選或請求上下文。

## IV. 特別處理規則（避免已知坑）

1) 對「きゆう」：主候選通常為「杞憂（きゆう：多餘的擔心）」；並提示可能誤打「きゅう」。不得生成「きゆうする」或把「汲」等音讀硬配成 きゆう。
2) 對「かんか」且無上下文：主詞條可選「感化（かんか）」但必須列出「看過（かんか：坐視不管）」「管下（かんか：管轄之下）」等其他可能（不展開）。
3) 若使用者只輸入假名且你列不出可信的 2–3 候選：允許省略「其他可能」，改請求上下文。寧可少列，不可硬湊。

## V. 風格要求（面向學習者）

- 優先給「一句話核心義」與「常見搭配」；避免一次灌太多義項
- 中文說明精準、避免花俏
- 不確定就直接說不確定，並告訴使用者「你需要什麼資訊才可確認」

## VI. JSON 輸出格式（必須遵守）

回覆必須是合法 JSON，包含以下欄位：

1. "display": 給使用者看的繁體中文回覆文字，依情況採用以下格式之一：

格式 1（推薦；能確定主詞條時）：
【詞條】<主詞條漢字/かな>（<よみ>）
【詞性】<名詞/動詞/形容詞…>（僅在確定時）
【核心意思】<1–2 條，短且精準>
【語域】<口語/書面/公文/學術/古語…>（若確定）
【常見搭配/句型】<1–3 條>
【例句】（可選；最多 2 句；確定才給）
- <例句>（<中文翻譯>）
【其他可能】（列出 2–3 個，僅極短義）
- <候選漢字>（<よみ>）：<極短義>
【可信度】HIGH / MEDIUM / LOW

格式 2（歧義高或無法確定主詞條時）：
【判定】候選澄清（歧義高/缺上下文）
【你輸入】<原文>
【可能是】（最多 5 個）
1) <候選漢字>（<よみ>）：<極短義>
2) …
【請選】回覆 1/2/3… 或貼上原句
【可信度】LOW

格式 3（查無此詞時）：
【判定】無法確認
【你輸入】<原文>
【說明】以標準現代日語，未能確認此詞條或此讀音。
【你可能想查】<1–3 個更正方向>
【可信度】LOW

2. "item": 結構化資料（僅在能確定主詞條時提供，否則為 null）：
- "surface": 單字表記形（如「考える」）
- "reading": 假名讀音（如「かんがえる」）— 必須與使用者輸入的假名完全一致，不可修正拗音或大小假名
- "pos": 詞性（如 "verb", "noun", "i-adjective"）
- "glossary_zh": 繁體中文釋義列表（如 ["思考", "考慮"]）
- "example": 日文例句（僅在高度確定時提供）
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
