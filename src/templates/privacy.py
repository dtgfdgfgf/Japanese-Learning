"""
Privacy policy text for LINE Bot.

T076: Create privacy policy text in src/templates/privacy.py
DoD: PRIVACY_TEXT 包含資料保存方式、LLM 使用說明、刪除方法
"""

PRIVACY_TEXT = """📋 隱私權說明

【資料保存】
• 您輸入的素材會被保存在安全的資料庫中
• 資料僅供您個人的學習紀錄使用
• 我們不會將您的資料分享給第三方

【AI 使用說明】
• 本服務使用 AI（Claude / Gemini）分析您的語言素材
• AI 會將您的內容轉換為單字和文法項目
• AI 分析過程中，您的內容會被傳送至 AI 服務商
• AI 不會記憶您的對話內容

【資料刪除】
• 輸入「刪除 <關鍵字>」刪除指定項目
• 輸入「清空資料」可刪除您的所有資料
• 刪除後資料無法恢復

【LINE 平台】
• 您的 LINE User ID 經過雜湊處理後儲存，無法還原
• 我們無法知道您的真實 LINE 帳號身分

如有疑問，請聯繫開發者。
"""

# Short version for quick reference
PRIVACY_SHORT = """📋 隱私簡述：
• 您的資料僅供個人學習使用
• AI 分析時會傳送至 AI 服務商
• 可隨時刪除您的資料

輸入「隱私」查看完整說明"""
