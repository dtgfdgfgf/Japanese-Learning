"""
Grader prompt template for LLM-based semantic answer evaluation.

用於練習系統的語義判定 fallback — 當嚴格匹配失敗時，
用 LLM 判斷使用者答案是否為該詞彙/文法的有效翻譯或意思。
"""

GRADER_SYSTEM_PROMPT = """你是語言學習練習的答案評分器。

題目會給出一個外語詞彙或文法，使用者需回答其中文意思（或反過來）。
你的任務是判斷：使用者的回答是否為該詞彙/文法的有效意思或翻譯。

注意：一個詞常有多種意思。例如：
- "problem" 可以是「問題」也可以是「麻煩」→ 兩者都算正確
- "run" 可以是「跑」「經營」「運行」→ 都算正確
- 「かける」可以是「掛」「打（電話）」「花費」→ 都算正確

規則：
- 只要回答是該詞的任一有效意思，就判正確
- 同義詞也算正確（「測試」≈「測驗」）
- 完全不相關的意思才判錯誤
- 嚴格以 JSON 格式回應，不要輸出其他文字"""


def format_grader_request(
    user_answer: str,
    expected_answer: str,
    accepted_answers: list[str],
    question_context: str,
) -> str:
    """格式化 grading 請求。

    Args:
        user_answer: 使用者的回答
        expected_answer: 主要預期答案
        accepted_answers: 所有已知可接受答案
        question_context: 題目 prompt（提供語境）

    Returns:
        格式化的 user message
    """
    accepted_str = "、".join(accepted_answers[:10])
    return (
        f"題目：{question_context}\n"
        f"已知正確答案：{accepted_str}\n"
        f"使用者回答：{user_answer}\n\n"
        f"使用者的回答是否為該詞彙的有效意思或翻譯？\n"
        f'請以 JSON 回應：{{"is_correct": true/false, "reason": "簡短理由"}}'
    )
