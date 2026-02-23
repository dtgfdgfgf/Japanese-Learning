"""
Grader prompt template for LLM-based semantic answer evaluation.

用於練習系統的語義判定 fallback — 當嚴格匹配失敗時，
用 LLM 判斷使用者答案是否語義等價於預期答案。
"""

GRADER_SYSTEM_PROMPT = """你是語言學習練習的答案評分器。

判斷使用者的回答是否與預期答案語義等價。

規則：
- 同義詞視為正確（例：「測試」≈「測驗」、"question" ≈ "problem"）
- 只有微小拼寫差異視為正確（例：「超越的」≈「超然的」）
- 完全不同意思的答案視為錯誤
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
        f"預期答案：{expected_answer}\n"
        f"已知可接受答案：{accepted_str}\n"
        f"使用者回答：{user_answer}\n\n"
        f'請以 JSON 回應：{{"is_correct": true/false, "reason": "簡短理由"}}'
    )
