# 10 個非理想操作 Edge Cases 模擬

## 狀態速查表

| 狀態 | 存儲 | Timeout | 設定時機 | 清除時機 |
|------|------|---------|---------|---------|
| `pending_save` | DB | 5 分鐘 | `_handle_unknown` 短單字流程 | 確認入庫 / 超時自動清 / 非"1"輸入時清 |
| `last_message` | DB | **永不過期** | post-dispatch（僅 UNKNOWN 指令） | `_handle_save` 消費後清 |
| `practice session` | DB | 30 分鐘 | 開始練習時 | 完成 / 超時 |

---

## Edge Case 1：單字 → 6 小時後 → 第二個單字（沒按 1）

**操作**：`"apple"` → 等 6 小時 → `"banana"`

**Step 1：`"apple"`**
```
parse_command → UNKNOWN
has_pending_save → FALSE
Dispatch #7 → _handle_unknown
  → classify: SAVE/0.9 → is_short_word → get_word_explanation ✓
  → set_pending_save("apple")
Post-dispatch: set_last_message("apple")
回覆：apple 解釋 + 「輸入1即可入庫」
```

**Step 2：`"banana"`（6 小時後）**
```
parse_command → UNKNOWN
has_pending_save → FALSE（5 分鐘 timeout 已過，自動清除）
Dispatch #7 → _handle_unknown
  → classify: SAVE/0.9 → is_short_word → get_word_explanation ✓
  → set_pending_save("banana")
Post-dispatch: set_last_message("banana")  ← 覆蓋 "apple"
回覆：banana 解釋 + 「輸入1即可入庫」
```

**結果**：`"apple"` 靜默丟失，無任何提示。`"banana"` 正常 pending。
**問題**：用戶可能以為 apple 已保存，實際沒有。

**✅ 已修復**：WORD_EXPLANATION 模板加上「請在 5 分鐘內」提示，讓用戶知道有時限。

---

## Edge Case 2：單字 → 立刻第二個單字（沒按 1）

**操作**：`"apple"` → 5 秒後 → `"banana"`

**Step 1：`"apple"`**（同 Case 1）
```
→ set_pending_save("apple")
→ set_last_message("apple")
回覆：apple 解釋 + 「輸入1即可入庫」
```

**Step 2：`"banana"`（5 秒後，pending_save 仍有效）**
```
parse_command → UNKNOWN
has_pending_save → TRUE（apple，<5 分鐘）
Dispatch #2：has_pending_save + 非 CONFIRM_SAVE
  → clear_pending_save（apple 被丟棄）
  → _dispatch_command(UNKNOWN) → _handle_unknown
  → classify: SAVE/0.9 → is_short_word → get_word_explanation ✓
  → set_pending_save("banana")
Post-dispatch: set_last_message("banana")  ← 覆蓋 "apple"
回覆：banana 解釋 + 「輸入1即可入庫」
```

**結果**：同 Case 1，`"apple"` 靜默丟失。
**差異**：pending_save 是被 dispatch #2 主動清除的，不是 timeout。

**✅ 已修復**：清除 pending 前取得舊內容，在回覆前加上「⚠️「apple」的入庫已取消。」通知。

---

## Edge Case 3：一條訊息輸入多個單字

**操作**：`"apple banana cherry"`（英文模式）

```
parse_command → UNKNOWN
has_pending_save → FALSE
Dispatch #7 → _handle_unknown
  → classify: LLM 判定 SAVE/0.8+
  → is_short_word: len=18, 有空格 → FALSE
  → 長文本分支：直接 save_raw("apple banana cherry")
Post-dispatch: set_last_message("apple banana cherry")
回覆：「已入庫... 輸入分析來抽取單字和文法」
```

**結果**：整段存為一筆 raw_message，不會分開處理。
**問題**：用戶預期三個單字各自解釋，實際被當成一段文本直接入庫。不會得到任何單字解釋。

**✅ 已修復**：偵測 2-5 個空格分隔短單字模式，處理第一個單字並提示「偵測到多個單字...請逐一輸入」。

---

## Edge Case 4：日文模式下輸入英文單字

**操作**：target_lang=`"ja"` 時輸入 `"sunshine"`

```
parse_command → UNKNOWN
Dispatch → _handle_unknown
  → classify("sunshine", target_lang="ja")
```

**若 LLM 成功**：LLM 可能仍判定為 SAVE（看 prompt 怎麼寫），有機會正常。

**若 LLM 失敗 → heuristic**：
```
stripped = "sunshine"
japanese_ratio = 0/8 = 0.0
english_ratio = 8/8 = 1.0

規則 1（問句）：否
規則 2（英文短單字）：target_lang="ja" ≠ "en" → 不匹配
規則 3（日文短詞）：japanese_ratio=0 → 不匹配
規則 4（日文長文）：不匹配
規則 5（英文長文）：target_lang="ja" ≠ "en" → 不匹配
規則 6（問句）：否
→ 預設：UNKNOWN/0.3
```

```
intent=UNKNOWN → 不匹配任何分支 → FALLBACK_UNKNOWN
回覆：「我不太確定你想做什麼」
```

**結果**：在日文模式下，英文單字完全無法被 heuristic 辨識。
**問題**：heuristic 的語言規則太嚴格——只認「目標語言」的內容。

**✅ 已修復**：新增跨語言備援規則，`target_lang≠"en" + english_ratio>0.8 + 3≤len≤30` → SAVE/0.85。

---

## Edge Case 5：「1」在 pending_save 超時後才輸入

**操作**：`"apple"` → 等 6 分鐘 → `"1"`

**Step 1：`"apple"`**
```
→ set_pending_save("apple")
→ 回覆：apple 解釋 + 「輸入1即可入庫」
```

**Step 2：`"1"`（6 分鐘後）**
```
parse_command → CONFIRM_SAVE
has_pending_save → get_pending_save() → elapsed=360s > 300s → 自動清除 → FALSE
Dispatch #3：CONFIRM_SAVE + NOT has_pending_save
  → _handle_unknown("1")
  → classify("1"): heuristic → "1" 長度 1 < 2 → 不匹配短單字 → UNKNOWN/0.3
  → FALLBACK_UNKNOWN
回覆：「我不太確定你想做什麼」
```

**結果**：用戶照著提示按了 1，卻被告知「不知道你想幹嘛」。
**問題**：沒有任何提示說明 pending 已過期。用戶完全困惑。

**✅ 已修復**：`CONFIRM_SAVE + 無 pending` → 回覆「沒有待入庫的內容（可能已超過 5 分鐘）。請重新輸入想查詢的單字。」

---

## Edge Case 6：單字解釋後查看說明 → 再按 1

**操作**：`"apple"` → `"說明"` → `"1"`

**Step 1：`"apple"`**
```
→ set_pending_save("apple")
→ 回覆：apple 解釋 + 「輸入1即可入庫」
```

**Step 2：`"說明"`**
```
parse_command → HELP
has_pending_save → TRUE（apple）
Dispatch #2：has_pending_save + 非 CONFIRM_SAVE
  → clear_pending_save（apple 被丟棄！）
  → _dispatch_command(HELP)
回覆：指令列表
```

**Step 3：`"1"`**
```
parse_command → CONFIRM_SAVE
has_pending_save → FALSE（已被 Step 2 清除）
Dispatch #3 → _handle_unknown("1") → FALLBACK_UNKNOWN
回覆：「我不太確定你想做什麼」
```

**結果**：用戶只是想看一下說明，回來按 1 卻發現 apple 沒了。
**問題**：**任何**非「1」的輸入都會清除 pending_save，包括無害的查看指令。

**✅ 已修復**：定義 `PENDING_SAFE_COMMANDS`（HELP, MODE_SWITCH, SET_LANG, COST, STATS, PRIVACY），這些指令不清除 pending_save。

---

## Edge Case 7：練習中輸入想查詢的單字

**操作**：練習進行中 → 輸入 `"vocabulary"`

```
parse_command → UNKNOWN
has_pending_save → FALSE
has_session → TRUE（練習中）
Dispatch #4：UNKNOWN + has_session → _handle_practice_answer("vocabulary")
  → 被當成練習答案處理
Post-dispatch: need_save_last_msg = UNKNOWN and NOT has_session = FALSE
  → last_message 不會被保存
回覆：批改結果（答錯）
```

**結果**：用戶想查單字，系統當成練習答案。
**問題**：練習模式下沒有查詢單字的途徑。`has_session` 優先級高於一切 UNKNOWN 輸入。

**✅ 已修復**：新增「結束練習」/「停止練習」指令（EXIT_PRACTICE），用戶可中途退出練習再查單字。說明訊息已加入此指令。

---

## Edge Case 8：單字解釋後輸入「入庫」而非「1」

**操作**：`"apple"` → `"入庫"`

**Step 1：`"apple"`**
```
→ set_pending_save("apple")
Post-dispatch: set_last_message("apple")  ← 關鍵！UNKNOWN 指令會存 last_message
回覆：apple 解釋 + 「輸入1即可入庫」
```

**Step 2：`"入庫"`**
```
parse_command → SAVE
has_pending_save → TRUE
Dispatch #2：has_pending_save + 非 CONFIRM_SAVE
  → clear_pending_save（丟棄 pending 的 "apple"）
  → _dispatch_command(SAVE) → _handle_save
  → get_last_message → "apple"（來自 Step 1 的 post-dispatch！）
  → save_raw("apple") → 成功
  → clear_last_message
回覆：「已入庫 ✅」
```

**結果**：apple 被成功入庫了！但走的是 `last_message` 路徑，不是 `pending_save` 路徑。
**微妙之處**：用戶感覺正常，但這是兩個狀態巧合配合的結果。如果 post-dispatch 沒存 last_message，這裡就會壞掉。

**✅ 已修復**：`SAVE + has_pending_save` 直接視為確認入庫（走 `_handle_confirm_save`），不再依賴 `last_message` 巧合路徑。

---

## Edge Case 9：切換模式時有 pending_save

**操作**：`"apple"` → `"免費模式"`

**Step 1：`"apple"`**
```
→ set_pending_save("apple")
回覆：apple 解釋 + 「輸入1即可入庫」
```

**Step 2：`"免費模式"`**
```
parse_command → MODE_SWITCH (keyword="免費模式")
has_pending_save → TRUE

Pre-dispatch：mode 已寫入 DB（line 184-192）✓

Dispatch #2：has_pending_save + 非 CONFIRM_SAVE
  → clear_pending_save（apple 丟棄）
  → _dispatch_command(MODE_SWITCH)
  → _dispatch_command 裡沒有 MODE_SWITCH handler！
  → 走到最後 line 440 → _handle_unknown("免費模式")
  → classify("免費模式"): 不是 SAVE → 可能是 UNKNOWN
  → FALLBACK_UNKNOWN
回覆：「我不太確定你想做什麼」
```

**結果**：
1. apple 的 pending_save 被清掉
2. 模式**實際上已切換成功**（pre-dispatch 處理了）
3. 但回覆是「我不太確定你想做什麼」而非模式切換確認訊息

**問題**：`_dispatch_command` 缺少 `MODE_SWITCH` 和 `SET_LANG` 的處理。這兩個只在 main dispatch 有 handler，但 pending_save 分支繞過了 main dispatch。

**✅ 已修復**：`MODE_SWITCH` 被加入 `PENDING_SAFE_COMMANDS`，不再進入 `_dispatch_command`，而是走到 main dispatch 的 MODE_SWITCH 分支。

---

## Edge Case 10：輸入單一字元（"I"、"a"、"字"）

**操作**：英文模式輸入 `"I"`

```
parse_command → UNKNOWN
Dispatch → _handle_unknown
  → classify("I", target_lang="en")
```

**若 LLM 成功**：可能判定為 SAVE → is_short_word → word explanation ✓

**若 LLM 失敗 → heuristic**：
```
stripped = "I"
english_ratio = 1.0
len("I") = 1

規則 2（英文短單字）：2 <= len <= 30 → 1 < 2 → 不匹配！
→ 預設：UNKNOWN/0.3
→ FALLBACK_UNKNOWN
```

**結果**：LLM 正常時可以查到 "I"，LLM 掛了就查不到。
**問題**：heuristic 的最小長度是 2，過濾掉了合理的單字元輸入。日文的「字」「雨」「愛」也是 1 個字元但可能想查。

**✅ 已修復**：英文模式 heuristic 最小長度從 2 降至 1。日文模式本就支援單一漢字（`japanese_ratio > 0.5 + len ≤ 15`）。

---

## Edge Case 11：Emoji 輸入（"🍎"）

**操作**：英文或日文模式輸入 `"🍎"`

```
parse_command("🍎") → UNKNOWN（無 regex 匹配）
has_pending_save → FALSE
Dispatch #7 → _handle_unknown
  → classify("🍎")
```

**若 LLM 失敗 → heuristic**：
```
stripped = "🍎"
🍎 = U+1F34E — 不在 CJK (\u4e00-\u9fff)、
                 不在 Hiragana (\u3040-\u309f)、
                 不在 Katakana (\u30a0-\u30ff) 範圍
japanese_chars = 0
ascii_alpha_chars = 0（emoji 不是 ASCII alpha）
total_chars = max(1, 1) = 1

japanese_ratio = 0, english_ratio = 0

所有規則均不匹配 → UNKNOWN/0.3
→ FALLBACK_UNKNOWN
```

```
Post-dispatch: set_last_message("🍎")  ← emoji 被存為 last_message
```

**結果**：用戶可能想查 🍎 的日文（りんご）或英文（apple），但 heuristic 完全無法辨識 emoji。
**延伸問題**：emoji 被存為 `last_message`，若用戶接著輸入「入庫」，一個 emoji 就被存入 DB，後續分析毫無意義。

**✅ 已修復**：`_has_meaningful_content()` 檢查攔截純 emoji 輸入，回覆引導訊息。同時不再將 emoji 存為 `last_message`。

---

## Edge Case 12：隱形字元（Zero-Width Space）混入文字

**操作**：從網頁複製貼上 `"apple"`，但文字中夾帶零寬空格（U+200B）：`"ap\u200Bple"`

用戶肉眼看到的是「apple」，完全不知道有隱形字元。

```
parse_command("ap​ple") → UNKNOWN

classify("ap​ple"):
  heuristic:
    stripped = "ap​ple"（strip() 不移除 ZWS，因為 ZWS 不是 Unicode whitespace）
    ascii_alpha = 5（a, p, p, l, e）
    total_chars = 6（5 字母 + 1 ZWS）
    english_ratio = 5/6 ≈ 0.83 > 0.8

    en short word: ' ' not in "ap​ple" → True ✓
    1 <= 6 <= 30 → True ✓
    → SAVE/0.85
```

**_handle_unknown**：
```
is_short_word = True
word = raw_text.strip() = "ap​ple"（ZWS 仍在）
→ get_word_explanation("ap​ple")  ← LLM 可能正常解釋
→ set_pending_save("ap​ple")      ← ZWS 跟著存入

用戶輸入「1」→ save_raw("ap​ple") → 含 ZWS 的文字存入 DB
```

**後續影響**：
```
查詢 apple → search_by_keyword("apple")
→ SQL LIKE '%apple%' 比對 "ap​ple"（中間有 ZWS）
→ 不匹配！搜尋不到！

Item 去重：unique key 也不同 → 同一個字可能被重複入庫
```

**結果**：用戶看不見的隱形字元導致儲存內容「看起來一樣但 bytes 不同」，搜尋和去重全部失效。
**問題**：沒有對輸入文字做 Unicode 正規化（strip zero-width characters）。

**✅ 已修復**：`_sanitize_text()` 在 `handle_message_event` 入口統一移除 ZWS / ZWNJ / BOM / Soft Hyphen / Word Joiner。

---

## Edge Case 13：指令多打字（"入庫了"、"分析一下"）

**操作**：日文模式下輸入 `"入庫了"`（多了一個中文「了」）

```
parse_command("入庫了"):
  Pattern ^入庫$: 嚴格匹配 → "入庫了" 不匹配
  所有 pattern 均不匹配 → UNKNOWN
```

```
classify("入庫了"):
  heuristic:
    入: U+5165 → CJK (\u4e00-\u9fff) ✓
    庫: U+5EAB → CJK ✓
    了: U+4E86 → CJK ✓

    japanese_chars = 3, total_chars = 3
    japanese_ratio = 3/3 = 1.0

    ja short word: japanese_ratio > 0.5 ✓, len(3) <= 15 ✓
    → SAVE/0.85
```

```
_handle_unknown:
  is_short_word = True
  → get_word_explanation("入庫了", target_lang="ja")
  → LLM：「入庫了」不是日文... 或嘗試牽強解釋
  → set_pending_save("入庫了")

回覆：（LLM 的困惑解釋）+ "輸入1即可入庫"
```

**結果**：用戶本意是觸發「入庫」指令，但因為多了一個字，變成要學「入庫了」這個「日文單字」。
**同類問題**：`"分析一下"` → 被當成學習素材、`"幫助我"` → 不是 HELP、`"練習吧"` → 不是 PRACTICE。

**✅ 已修復**：`_suggest_command()` 偵測開頭匹配指令但有多餘字元（≤5 字元差距）的輸入，回覆「你可能想輸入指令 X」引導。

---

## Edge Case 14：純空白或純符號輸入（"   "、"..."、"！！！"）

**操作**：輸入三個空格 `"   "`

```
parse_command("   "):
  normalized = "   ".strip() = ""
  所有 pattern 均不匹配空字串 → UNKNOWN（raw_text="   "）

classify("   "):
  heuristic:
    stripped = "" (strip 後為空)
    total_chars = max(len("".replace(" ", "")), 1) = max(0, 1) = 1
    japanese_ratio = 0, english_ratio = 0
    → UNKNOWN/0.3
    → FALLBACK_UNKNOWN

Post-dispatch:
  need_save_last_msg = True（UNKNOWN + no session）
  → set_last_message("   ")   ← 空白被存為 last_message！
```

**若用戶接著輸入「入庫」**：
```
_handle_save:
  → get_last_message → "   "
  → save_raw("   ") → 存入 DB！
  → content_preview = "   ".split('\n')[0].strip() = ""
  → 回覆：「已入庫：」← 冒號後面是空的
```

**同類問題**：`"..."`, `"！！！"`, `"~~~"` 等純符號也會被存為 `last_message`，可被「入庫」。

**結果**：無意義的空白/符號內容被靜默存入資料庫，後續分析完全無用。
**問題**：沒有對輸入內容做最低有效性檢查（至少要包含字母/漢字/假名）。

**✅ 已修復**：`_has_meaningful_content()` 在三處防堵——(1) `_handle_unknown` 入口攔截、(2) post-dispatch 不存為 `last_message`、(3) `_handle_save` 拒絕無意義內容。

---

## Edge Case 15：多行單字列表（每行一個單字）

**操作**：從筆記 app 複製貼上，每行一個英文單字：
```
apple
banana
cherry
```

實際輸入文字為 `"apple\nbanana\ncherry"`

```
parse_command → UNKNOWN

classify("apple\nbanana\ncherry"):
  heuristic:
    stripped = "apple\nbanana\ncherry"
    ascii_alpha = 17（a,p,p,l,e,b,a,n,a,n,a,c,h,e,r,r,y）
    total_chars = max(len("apple\nbanana\ncherry".replace(" ", "")), 1) = 19
    english_ratio = 17/19 ≈ 0.89

    en short word (target_lang="en"):
      ' ' not in "apple\nbanana\ncherry" → True ← 關鍵！換行 ≠ 空格
      english_ratio > 0.8 → True ✓
      1 <= 19 <= 30 → True ✓
      → SAVE/0.85
```

```
_handle_unknown:
  stripped_text = "apple\nbanana\ncherry"
  is_short_word:
    len(19) <= 30 → True
    ' ' not in stripped_text → True（只有 \n，沒有空格）
    → is_short_word = True  ← 三個單字被當成一個「單字」！

  → get_word_explanation("apple\nbanana\ncherry")
  → LLM 收到三行文字，嘗試解釋為一個詞，結果混亂
  → set_pending_save("apple\nbanana\ncherry")
```

**多單字偵測路徑（line 748）在 else 分支，永遠不會被觸發**：
```
is_multi_word 邏輯：
  tokens = stripped_text.split()  ← split() 會分割換行
  → ["apple", "banana", "cherry"]  ← 理論上能偵測到 3 個單字
  但此分支在 is_short_word 的 else 裡，已經被跳過
```

**結果**：`' '`（ASCII 空格）檢查不包含 `\n`（換行），導致換行分隔的多單字列表被當成單一「單字」處理。
**問題**：`is_short_word` 和多單字偵測只看 ASCII 空格，不看其他 whitespace。

**✅ 已修復**：`is_short_word` 和 heuristic 的 `' ' not in` 改為 `len(text.split()) == 1`，涵蓋空格、換行、Tab 等所有 whitespace。

---

## Edge Case 16：半形片假名輸入（"ﾎﾟｹｯﾄ"）

**操作**：日文模式輸入半形片假名 `"ﾎﾟｹｯﾄ"`（＝ ポケット/pocket）

來源：舊系統 copy-paste、某些 IME 設定、部分 CSV/DB 匯出

```
parse_command → UNKNOWN

classify("ﾎﾟｹｯﾄ"):
  heuristic:
    ﾎ: U+FF8E — Halfwidth Katakana Letter Ho
    ﾟ: U+FF9F — Halfwidth Katakana Semi-Voiced Sound Mark
    ｹ: U+FF79 — Halfwidth Katakana Letter Ke
    ｯ: U+FF6F — Halfwidth Katakana Letter Small Tu
    ﾄ: U+FF84 — Halfwidth Katakana Letter To

    半形片假名範圍：U+FF65-U+FF9F
    heuristic 的日文字元偵測範圍：
      - Hiragana: \u3040-\u309f ✗
      - Katakana: \u30a0-\u30ff ✗（半形不在此範圍！）
      - CJK:      \u4e00-\u9fff ✗

    japanese_chars = 0  ← 全部漏掉！
    ascii_alpha = 0
    total_chars = 5

    japanese_ratio = 0, english_ratio = 0
    所有規則均不匹配 → UNKNOWN/0.3
    → FALLBACK_UNKNOWN
```

**對比全形**：
```
ポケット（U+30DD, U+30B1, U+30C3, U+30C8）
→ 全在 \u30a0-\u30ff 範圍 → japanese_chars = 4 → SAVE/0.85 ✓
```

**結果**：合法的日文片假名內容，僅因為是「半形」就被 heuristic 完全無視。
**問題**：`japanese_chars` 的 Unicode 範圍漏掉了半形片假名（U+FF65-U+FF9F）。

**✅ 已修復**：heuristic 的 `kana_chars` 偵測加入半形片假名範圍 `\uff65 <= c <= \uff9f`。

---

## Edge Case 17：中文文字被誤判為日文（"你好嗎"）

**操作**：日文模式下輸入中文 `"你好嗎"`

```
parse_command → UNKNOWN

classify("你好嗎"):
  heuristic:
    你: U+4F60 → \u4e00-\u9fff (CJK Unified) → japanese_char ✓
    好: U+597D → CJK → japanese_char ✓
    嗎: U+55CE → CJK → japanese_char ✓

    japanese_chars = 3, total_chars = 3
    japanese_ratio = 1.0

    ja short word: japanese_ratio > 0.5 ✓, len(3) <= 15 ✓
    → SAVE/0.85
```

```
_handle_unknown:
  is_short_word = True
  → get_word_explanation("你好嗎", target_lang="ja")
  → LLM（日語老師 prompt）：收到中文「你好嗎」
  → 可能回覆：「這不是日文，是中文，意思是...」或勉強解釋
  → set_pending_save("你好嗎")

回覆：（困惑的解釋）+ "輸入1即可入庫"
```

**若用戶確認入庫**：中文內容被存為「日文學習素材」。後續分析/練習會產生莫名其妙的結果。

**結果**：CJK Unified Ideographs（U+4E00-U+9FFF）涵蓋中文漢字、日文漢字、韓文漢字，heuristic 無法區分。
**問題**：`japanese_ratio` 其實是「CJK 字元比率」，非真正的「日文比率」。純中文（你、嗎、吧、了、么）或韓文漢字都會被誤認為日文。

**✅ 已修復**：拆分 `kana_chars` / `cjk_chars` 計數。有假名 → confidence 0.85（確定日文）；純漢字無假名 → confidence 0.7（低於 0.8 閾值，不進入短單字解釋流程）。LLM 正常時仍可正確處理。

---

## Edge Case 18：純 URL 輸入

**操作**：日文模式下貼上新聞連結 `"https://www3.nhk.or.jp/news/html/20240115/k10014322341000.html"`

```
parse_command → UNKNOWN

classify(URL):
  heuristic:
    stripped = "https://www3.nhk.or.jp/news/html/20240115/k10014322341000.html"
    ascii_alpha ≈ 28（h,t,t,p,s,w,w,w,n,h,k,...）
    total_chars ≈ 58（含數字、斜線、點等）
    english_ratio = 28/58 ≈ 0.48

    所有規則：
    - en short word: english_ratio = 0.48 < 0.8 → 不匹配
    - en long text: english_ratio = 0.48 < 0.5 → 不匹配（邊界值！）
    - 其他規則: 不匹配
    → UNKNOWN/0.3 → FALLBACK_UNKNOWN
```

**若 LLM 成功判定 SAVE/0.9**：
```
is_short_word: len ≈ 58 > 30 → False
is_multi_word: tokens = [整段 URL] → len = 1 → False
→ 長文本分支：save_raw(URL 字串)
→ 回覆：「已入庫：https://www3.nhk.or.jp/...」

用戶後續「分析」：
→ ExtractorService 收到一串 URL，不是文章內容
→ 無法抽取任何單字或文法
→ ANALYZE_EMPTY_RESULT 或錯誤
```

**結果**：系統不會讀取 URL 指向的內容，只是把 URL 字串本身存入 DB。用戶預期系統能「讀取文章」，實際只存了網址。
**問題**：沒有 URL 偵測邏輯。可區分兩種策略：(1) 提示用戶「請貼上文章內容而非連結」；(2) 未來支援 URL 抓取。

**✅ 已修復**：`_is_url()` 偵測 `http://` / `https://` 開頭的輸入，回覆「請複製文章的文字內容後貼上」引導。

---

## Edge Case 19：快速連發訊息（Production 背景處理競爭）

**操作**：Production 環境下，用戶極快速連發：
- Message 1：`"apple"`（查詢單字）
- Message 2：`"1"`（確認入庫，<100ms 後發送）

**Production 的背景處理機制**（`webhook.py` line 107-113）：
```python
background = os.environ.get("RENDER_EXTERNAL_HOSTNAME") is not None
if background:
    asyncio.create_task(_safe_handle_message(event))  # 背景執行，不等完成
```

**Scenario A：Message 2 先處理完 pre-dispatch**：
```
Task 2 ("1")：
  parse_command("1") → CONFIRM_SAVE
  has_pending_save → FALSE（Task 1 還沒設定 pending_save！）
  → Dispatch: CONFIRM_SAVE + not has_pending_save
  → 回覆：「沒有待入庫的內容（可能已超過 5 分鐘）」

Task 1 ("apple")（稍後完成）：
  → word_explanation + set_pending_save("apple")
  → 回覆：「apple 的意思... 輸入1即可入庫」
```

**用戶看到的訊息順序**：
1. ❌「沒有待入庫的內容」（莫名其妙）
2. 「apple 的意思... 輸入1即可入庫」（正常，但 "1" 已經用掉了）

用戶必須再輸入一次 "1"。

**Scenario B：Message 1 先完成（正常順序）**：一切正確。

**結果**：在高延遲或高負載下，`asyncio.create_task` 不保證執行順序。`pending_save` 狀態可能在確認訊息處理時尚未寫入 DB。
**問題**：背景 task 之間共享 DB 狀態但無同步機制。兩個 message event 若來自同一用戶，應該序列化處理。

**✅ 已修復**：`_user_locks` dict + `asyncio.Lock()` per-user 序列化，`_safe_handle_message` / `_safe_handle_postback` 都套用。

---

## Edge Case 20：試算表複製貼上（TSV / 混合語言格式）

**操作**：從 Excel 或 Google Sheets 複製一行：`"食べる\tたべる\tto eat"`（Tab 分隔）

```
parse_command → UNKNOWN

classify("食べる\tたべる\tto eat"):
  heuristic:
    japanese_chars: 食,べ,る,た,べ,る = 6
    ascii_alpha: t,o,e,a,t = 5
    total_chars = len("食べる\tたべる\ttoeat") = 16
      （.replace(" ", "") 只移除空格，Tab 保留）

    japanese_ratio = 6/16 = 0.375
    english_ratio = 5/16 = 0.3125

    規則判定：
    - ja short word: japanese_ratio = 0.375 < 0.5 → 不匹配
    - en short word: english_ratio = 0.3125 < 0.8 → 不匹配
    - ja long text: japanese_ratio = 0.375 < 0.5 → 不匹配
    - en long text: english_ratio = 0.3125 < 0.5 → 不匹配
    - cross-lang: english_ratio = 0.3125 < 0.8 → 不匹配
    - 問句: 否

    → UNKNOWN/0.3 → FALLBACK_UNKNOWN
```

**即使 LLM 成功判定 SAVE/0.9**：
```
stripped_text = "食べる\tたべる\tto eat"
' ' in stripped_text → True（"to eat" 中間有空格）
is_short_word = False

tokens = stripped_text.split() → ["食べる", "たべる", "to", "eat"]
is_multi_word: 2 <= 4 <= 5 ✓
  但 all(t.isalpha() ...) → "食べる".isalpha() = True（Python 3 CJK 算 alpha）
  → is_multi_word = True
  → 只處理第一個 token「食べる」，提示其餘逐一輸入

但用戶的意圖是把「食べる / たべる / to eat」當成一筆完整素材入庫，不是四個獨立單字。
```

**結果**：
- heuristic 路徑：混合語言內容稀釋了各語言比率，全部低於閾值，直接 FALLBACK。
- LLM 路徑：被多單字偵測拆開，破壞了原本的「單字 + 讀音 + 翻譯」結構。
**問題**：系統不理解結構化的學習資料格式（TSV、CSV）。Tab 分隔的一行資料被當成「多個獨立單字」處理，丟失了讀音和翻譯的關聯。

**✅ 已修復**：`_handle_unknown` 偵測 `\t` 存在時，跳過 router 直接 `save_raw()` 入庫，保留結構化格式。

---

## Edge Case 21：全形英數字輸入（"ａｐｐｌｅ"）

**操作**：日文 IME 開啟狀態下輸入 `"ａｐｐｌｅ"`（全形英文字母）

用戶在手機或桌面的日文 IME 中輸入英文，若未切回半形模式，所有字母會自動變成全形：`a` → `ａ`（U+FF41）。

```
parse_command("ａｐｐｌｅ") → UNKNOWN

classify("ａｐｐｌｅ"):
  heuristic:
    ａ: U+FF41 — Fullwidth Latin Small Letter A
    ｐ: U+FF50 — Fullwidth Latin Small Letter P
    ...

    c.isascii() → False（全形字元不在 ASCII 範圍）
    ascii_alpha_chars = 0  ← 全部漏掉！

    Hiragana/Katakana/CJK 範圍也不包含全形英文
    kana_chars = 0, cjk_chars = 0

    japanese_ratio = 0, english_ratio = 0

    所有規則均不匹配 → UNKNOWN/0.3
    → FALLBACK_UNKNOWN
```

**LLM 路徑**：LLM 通常能正確理解全形英文，判定為 SAVE。但 heuristic 完全無法辨識。

**延伸**：全形數字 `１`（U+FF11）也不匹配 `^1$` regex → `parse_command("１")` 回傳 UNKNOWN。用戶按了全形的 1 卻無法確認入庫。

**結果**：全形英文被 heuristic 視為不可辨識字元。全形數字無法觸發任何指令。
**問題**：`_sanitize_text()` 和 heuristic 都沒有做 NFKC 正規化（將全形轉為半形）。

**✅ 已修復**：`_sanitize_text()` 加入 `unicodedata.normalize('NFKC', text)` 將全形英數轉為半形。

---

## Edge Case 22：混合語言句子（"appleは美味しい"）

**操作**：日文模式下輸入 `"appleは美味しい"`（英日混合句）

這是自然的日語用法，外來語或英文常混入日文句中。

```
parse_command → UNKNOWN

classify("appleは美味しい"):
  heuristic:
    a,p,p,l,e → ascii_alpha = 5
    は: U+306F → Hiragana → kana_chars++
    美: U+7F8E → CJK → cjk_chars++
    味: U+5473 → CJK → cjk_chars++
    し: U+3057 → Hiragana → kana_chars++
    い: U+3044 → Hiragana → kana_chars++

    kana_chars = 3, cjk_chars = 2
    japanese_chars = kana_chars + cjk_chars = 5
    ascii_alpha_chars = 5
    total_chars = max(len("appleは美味しい".replace(" ", "")), 1) = 10

    japanese_ratio = 5/10 = 0.5
    english_ratio = 5/10 = 0.5

    規則判定：
    - ja short word: japanese_ratio > 0.5 → 0.5 不大於 0.5 → 不匹配！
    - en short word: target_lang="ja" ≠ "en" → 不匹配
    - ja long text: len(10) > 10? → 不匹配（邊界值！）
    - cross-lang: english_ratio = 0.5 < 0.8 → 不匹配
    → UNKNOWN/0.3
```

**LLM 正常時**：可能判定 SAVE/0.9 → 長度 10, 非 single token → `is_short_word = False`
→ 非多單字（含日文字元）→ 長文本分支 → `save_raw("appleは美味しい")`

**結果**：heuristic 因為日英比率各佔一半，兩邊都達不到閾值，直接 FALLBACK。LLM 正常時可處理但走的是「長文本直接入庫」路徑，用戶不會得到單字解釋。
**問題**：`japanese_ratio > 0.5` 的嚴格大於（不含等於）導致剛好 50:50 混合時兩邊都不匹配。混合語言句子是日語學習中非常常見的場景。

**✅ 已修復**：`japanese_ratio > 0.5` 改為 `japanese_ratio >= 0.5`（兩處），50:50 混合語言不再被遺漏。

---

## Edge Case 23：Romaji 輸入（"watashi wa gakusei desu"）

**操作**：日文模式下輸入 `"watashi wa gakusei desu"`（忘了開啟 IME 轉換）

常見情境：手機切換到英文鍵盤打日語讀音、或桌面 IME 的直接輸入模式。

```
parse_command → UNKNOWN

classify("watashi wa gakusei desu"):
  heuristic:
    全部是 ASCII 字母和空格
    ascii_alpha_chars = 22（w,a,t,a,s,h,i,w,a,g,a,k,u,s,e,i,d,e,s,u）
    total_chars = max(len("watashiwagakuseidesu"), 1) = 20

    english_ratio = 22/20 → 超過 1.0（空格不算 total 但算 alpha）
    → 實際上 total_chars = max(20, 1) = 20, english_ratio = min(22/20, 1.0) 或直接 22/20

    target_lang = "ja"

    規則判定：
    - cross-lang: english_ratio > 0.8 ✓, target_lang ≠ "en" ✓
      len = 24（含空格）, 3 <= 24 <= 30 ✓
      → SAVE/0.85
```

```
_handle_unknown:
  is_short_word:
    len("watashi wa gakusei desu") = 24 <= 30（英文模式閾值，但 target_lang="ja"）
    實際用 ja 閾值：len <= 15 → 24 > 15 → False
    或用跨語言邏輯 len <= 30 → True
    split() = ["watashi", "wa", "gakusei", "desu"] → len = 4 ≠ 1 → False

  is_short_word = False

  is_multi_word:
    tokens = ["watashi", "wa", "gakusei", "desu"]
    2 <= 4 <= 5 ✓
    all(t.isalpha()) ✓
    → is_multi_word = True
    → 只處理 "watashi"，提示其餘逐一輸入
```

**結果**：`"watashi wa gakusei desu"` 被拆成 4 個「英文單字」，系統嘗試解釋 "watashi" 的英文意思（不存在的英文單字）。用戶的意圖是輸入日文「私は学生です」。
**問題**：系統無法辨識 Romaji（日語羅馬字拼音）。Romaji 看起來像英文但語義完全不同。常見的 Romaji 模式如「wa」「desu」「masu」不會被特別處理。

**✅ 已修復**：`_is_likely_romaji()` 偵測常見 Romaji 助詞/語尾（≥2 hits），回覆「看起來是日語的羅馬字拼音，請開啟日文輸入法」。

---

## Edge Case 24：非「1」的數字輸入（"2"、"3"、"0"）

**操作**：單字解釋後輸入 `"2"`（以為有多個選項）

常見心理：看到「輸入 1 即可入庫」，以為還有選項 2（不入庫）或 3（其他操作）。

**Step 1：`"apple"` → 正常流程，得到解釋 + 「輸入1即可入庫」**

**Step 2：`"2"`**
```
parse_command("2"):
  Pattern ^1$: "2" ≠ "1" → 不匹配
  所有 pattern 均不匹配 → UNKNOWN（raw_text="2"）

has_pending_save → TRUE（apple）
Dispatch #2：has_pending_save + 非 CONFIRM_SAVE + 非 PENDING_SAFE
  → old_content = get_pending_content()  ← "apple"
  → clear_pending_save
  → _dispatch_command(UNKNOWN, "2")
    → _handle_unknown("2")
    → classify("2"):
        heuristic:
          ascii_alpha_chars = 0（"2" 不是字母）
          japanese_chars = 0
          → UNKNOWN/0.3
    → FALLBACK_UNKNOWN
回覆：「⚠️「apple」的入庫已取消。」+「我不太確定你想做什麼」
```

**結果**：用戶只是選了「第二個選項」（不存在），apple 的 pending 被清掉，並收到困惑的回覆。
**問題**：(1) 提示訊息只說「輸入 1」，沒有明確說「這是唯一操作」或「輸入其他內容即取消」。(2) 數字 2-9 在 pending 狀態下沒有特殊處理。

**✅ 已修復**：pending 狀態下收到單一數字 0/2-9 時，回覆「只有輸入『1』可以確認入庫」提示，不清除 pending。

---

## Edge Case 25：引號包裹輸入（「食べる」、"apple"）

**操作**：日文模式下輸入 `"「食べる」"`（用中文引號包裹單字）

常見習慣：用戶為了強調或區分，用引號把要查詢的字包起來。

```
parse_command("「食べる」") → UNKNOWN

classify("「食べる」"):
  heuristic:
    「: U+300C — CJK Left Corner Bracket → 不在任何範圍
    食: U+98DF → CJK → cjk_chars++
    べ: U+3079 → Hiragana → kana_chars++
    る: U+308B → Hiragana → kana_chars++
    」: U+300D — CJK Right Corner Bracket → 不在任何範圍

    kana_chars = 2, cjk_chars = 1
    japanese_chars = 3
    total_chars = max(len("「食べる」".replace(" ", "")), 1) = 5

    japanese_ratio = 3/5 = 0.6 > 0.5 ✓
    len(5) <= 15 ✓
    → kana_chars > 0 → SAVE/0.85
```

```
_handle_unknown:
  stripped_text = "「食べる」"
  is_short_word:
    target_lang="ja" → len(5) <= 15 ✓
    split() = ["「食べる」"] → len = 1 ✓
    → is_short_word = True

  → get_word_explanation("「食べる」", target_lang="ja")
  → LLM 收到帶引號的單字，可能正常解釋或被引號干擾
  → set_pending_save("「食べる」")  ← 引號跟著存入！
```

**若用戶確認入庫**：
```
save_raw("「食べる」") → DB 中存的是帶引號的內容

後續搜尋：search_by_keyword("食べる")
  → SQL LIKE '%食べる%' 比對 "「食べる」" → 匹配 ✓（引號不影響 LIKE）

但 Item 去重：key = "「食べる」" ≠ "食べる" → 可能重複入庫！
```

**同類問題**：`"apple"`（英文引號）、`『食べる』`（雙角引號）、`【apple】`（方括號）

**結果**：引號不影響 heuristic 判定，但會跟著存入 DB，造成去重 key 不一致。LLM 解釋品質也可能受引號干擾。
**問題**：沒有在處理前剝除常見的引號/括號字元。

**✅ 已修復**：`_strip_outer_quotes()` 在 `_sanitize_text()` 中剝除首尾成對引號/括號（「」『』""''【】（）〈〉），只剝一層。

---

## Edge Case 26：超長文本貼上（5000+ 字元）

**操作**：從新聞網站複製一整篇日文文章（8000 字元），貼上送出。

```
parse_command → UNKNOWN

classify(8000字元文本):
  LLM 路徑：
    → RouterService 送 8000 字給 LLM
    → LLM prompt 包含完整文本 → token 數爆增（~3000-4000 tokens）
    → 分類結果：SAVE/0.95（長文本，判定為素材）
    → LLM 費用：僅做分類就消耗大量 tokens

  heuristic 路徑：
    → japanese_ratio 高 → ja long text → SAVE/0.6
    → confidence < 0.8 → 不進短單字流程 → 直接入庫 ✓
```

```
_handle_unknown:
  classification.intent = SAVE
  is_short_word = False（len > 15）
  is_multi_word = False（token 數 > 5）

  → 長文本分支：save_raw(8000字元文本)
  → save_raw 內部：set_last_message(text[:5000])  ← 截斷至 5000！
  → 但 raw_message 本身存完整內容？需視 DB column 限制

Post-dispatch:
  → set_last_message(text[:5000])  ← 截斷
```

**後續分析**：
```
用戶輸入「分析」
→ get_last_message → 截斷後的 5000 字文本
→ ExtractorService 送 5000 字給 LLM
→ LLM 需要處理大量文本 → 費用高、可能 timeout
→ 若使用免費模式：可能超出 rate limit
```

**結果**：(1) Router 分類就消耗大量 LLM tokens（浪費）。(2) `last_message` 被截斷至 5000 字，剩餘 3000 字靜默丟失。(3) 後續分析的 LLM 費用和 timeout 風險大幅增加。
**問題**：沒有對輸入文本設定合理長度上限。Router 不需要完整文本來做分類（前幾百字就夠了）。

**✅ 已修復**：超過 2000 字時跳過 Router 直接 `save_raw()`，回覆含字數提示。

---

## Edge Case 27：非文字訊息（貼圖、圖片、語音、位置）

**操作**：用戶傳送一張日文菜單的照片，想讓 Bot 幫忙辨識翻譯。

```python
# webhook.py line 227-228
if not isinstance(event.message, TextMessageContent):
    return  ← 直接 return，無任何回覆
```

**結果**：用戶傳了圖片後，Bot 完全沒有反應。沒有已讀、沒有回覆、沒有錯誤訊息。

**常見場景**：
- 📷 拍照日文菜單/路牌/書本 → 沒反應
- 🎤 語音訊息說日文 → 沒反應
- 😊 傳貼圖打招呼 → 沒反應
- 📍 傳位置分享 → 沒反應
- 📄 傳 PDF 檔案 → 沒反應

**用戶心理**：「Bot 壞了？」「為什麼不理我？」反覆嘗試 → 仍然沒反應 → 放棄使用。

**問題**：非文字訊息被靜默忽略，沒有任何反饋。用戶無法知道 Bot 只支援文字輸入。

**✅ 已修復**：非文字訊息回覆「目前僅支援文字訊息，請將想查詢的內容以文字方式輸入。」

---

## Edge Case 28：LINE Webhook 重複送達（Retry 機制）

**操作**：用戶正常發送 `"apple"`，但 Bot 伺服器處理較慢（>1 秒），LINE 平台認為未收到回應，自動重送同一 webhook event。

**LINE 的 Retry 機制**：
- 若 webhook endpoint 在 **1 秒**內未回傳 HTTP 200，LINE 會重試
- 重試間隔：約 1 秒、2 秒、4 秒（指數退避）
- 最多重試 **3 次**

```
Request 1（原始）：
  event.webhook_event_id = "evt_abc123"
  → asyncio.create_task(_safe_handle_message(event))
  → return 200（立即回傳，背景處理）

  背景 Task 1：
  → _handle_unknown("apple")
  → classify → LLM 呼叫中（需 2-5 秒）...

Request 2（LINE retry，1 秒後）：
  event.webhook_event_id = "evt_abc123"（同一 event ID）
  → asyncio.create_task(_safe_handle_message(event))  ← 又建了一個 task！

  背景 Task 2（與 Task 1 平行執行）：
  → _handle_unknown("apple")
  → classify → 又一次 LLM 呼叫！
```

**若兩個 Task 都完成**：
```
Task 1 結果：
  → word_explanation("apple") → 回覆 1
  → set_pending_save("apple")

Task 2 結果：
  → word_explanation("apple") → 回覆 2（重複回覆！）
  → set_pending_save("apple")（覆蓋，但內容相同）
```

**用戶看到**：同樣的解釋訊息出現**兩次**（或更多次）。
**更糟的情境**：若 Request 1 處理到一半設了 pending_save，Request 2 的 has_pending_save 檢查可能為 TRUE → 走 dispatch #2 → 清除 pending → 混亂。

**結果**：(1) 重複回覆讓用戶困惑。(2) 重複 LLM 呼叫浪費費用。(3) 狀態競爭可能導致不可預測的行為。
**問題**：沒有 webhook event 去重機制。LINE 提供 `x-line-retry-key` header 和 `webhook_event_id` 可用於辨識重複事件。

**✅ 已修復**：`_is_duplicate_event()` 用 in-memory dict + 60 秒 TTL 追蹤 `webhookEventId`，重複事件直接跳過。

---

## Edge Case 29：韓文 Hangul 輸入（"한국어"）

**操作**：日文模式下輸入韓文 `"한국어"`（韓國語）

可能情境：用戶是韓國人學日文、手機鍵盤切到韓文、或故意測試。

```
parse_command → UNKNOWN

classify("한국어"):
  heuristic:
    한: U+D55C → Hangul Syllable（U+AC00-U+D7AF）
    국: U+AD6D → Hangul Syllable
    어: U+C5B4 → Hangul Syllable

    Hiragana (\u3040-\u309f)? 否
    Katakana (\u30a0-\u30ff)? 否
    Half-width Katakana (\uff65-\uff9f)? 否
    CJK (\u4e00-\u9fff)? 否（Hangul 不在 CJK Unified 範圍！）
    ASCII alpha? 否

    kana_chars = 0, cjk_chars = 0, ascii_alpha = 0
    japanese_ratio = 0, english_ratio = 0

    → UNKNOWN/0.3 → FALLBACK_UNKNOWN
```

**但 `_has_meaningful_content()` 檢查**：
```python
any(c.isalpha() for c in "한국어")
  → "한".isalpha() → True（Python 3 的 isalpha() 認定 Hangul 為字母）
  → 回傳 True → 通過有效性檢查
```

**Post-dispatch**：
```
need_save_last_msg = True（UNKNOWN + no session）
→ set_last_message("한국어")  ← 韓文被存為 last_message！
```

**若用戶接著輸入「入庫」**：
```
→ get_last_message → "한국어"
→ save_raw("한국어") → 韓文存入日文學習 DB！
→ 後續分析：LLM 收到韓文，以日語老師身份嘗試分析 → 混亂結果
```

**結果**：韓文通過 `_has_meaningful_content()` 但被 heuristic 判定 UNKNOWN。FALLBACK 後靜默存為 `last_message`，可被後續「入庫」操作存入 DB。
**問題**：`_has_meaningful_content()` 使用 Python 的 `.isalpha()` 判斷——它認為所有 Unicode 字母（包括韓文、泰文、阿拉伯文等）都是「有意義的」，但 heuristic 和後續流程只能處理日文和英文。

**✅ 已修復**：新增 `_has_supported_language_content()` 檢查字元是否屬於支援語言（ASCII + CJK + 假名），非支援語言回覆「目前支援日文和英文內容」。

---

## Edge Case 30：手機自動修正 / 預測輸入（"aple" → "able"）

**操作**：英文模式下想輸入 `"aple"`（apple 的拼錯），手機自動修正為 `"able"`

手機鍵盤的自動修正功能會在用戶不注意時替換「不認識的字」為最接近的字典單字。

```
用戶意圖：查詢 "apple"（手滑打成 "aple"）
手機實際發送："able"（自動修正後）

parse_command("able") → UNKNOWN

classify("able"):
  heuristic:
    ascii_alpha = 4, total_chars = 4
    english_ratio = 1.0
    target_lang = "en"
    en short word: 1 <= 4 <= 30 ✓, single token ✓, ratio > 0.8 ✓
    → SAVE/0.85

_handle_unknown:
  is_short_word = True
  → get_word_explanation("able")
  → LLM：「able 是形容詞，意思是『能夠的、有能力的』...」
  → set_pending_save("able")

回覆：able 的完美解釋 + 「輸入1即可入庫」
```

**用戶看到 "able" 的解釋**：
- 用戶：「我明明輸入的是 apple 啊？」
- 回頭看自己的訊息氣泡：顯示 "able"（已被手機改掉）
- 不理解為什麼查到錯誤的字

**更隱蔽的案例**：
```
日文模式：
  用戶想打 "taberu"（食べる）但 IME 未開
  手機修正："taberu" → "table"（英文自動修正）
  → 系統查詢 "table" 的英文解釋
  → 用戶完全困惑
```

**結果**：自動修正發生在 LINE client 端，Bot 收到的已經是修正後的文字，完全無法察覺原始意圖。系統的回覆在技術上完全正確，但不是用戶想要的。
**問題**：這是 client 端行為，伺服器端無法直接解決。但可以透過 UX 設計降低影響。

**✅ 已修復**（UX 層面）：WORD_EXPLANATION 模板加入「若非你要查的字，請重新輸入正確的拼寫」提示，降低用戶困惑。

---

## 問題總結

| # | Edge Case | 結果 | 嚴重度 | 根因 | 修復狀態 |
|---|-----------|------|--------|------|---------|
| 1 | 單字→久→第二個單字 | 第一個靜默丟失 | 中 | pending_save 超時無通知 | ✅ 已修（提示 5 分鐘時限） |
| 2 | 單字→馬上第二個 | 第一個靜默丟失 | 中 | 非"1"輸入一律清 pending | ✅ 已修（取消通知） |
| 3 | 一條訊息多個單字 | 整段存為 blob | 低 | 無多單字偵測 | ✅ 已修（多單字偵測） |
| 4 | 日文模式送英文 | heuristic 死路 | **高** | heuristic 只認目標語言 | ✅ 已修（跨語言規則） |
| 5 | 1 超時了才按 | 困惑的 FALLBACK | **高** | 無過期提示 | ✅ 已修（過期提示） |
| 6 | 查說明後按 1 | pending 被清 | **高** | 所有非"1"都清 pending | ✅ 已修（安全指令白名單） |
| 7 | 練習中查單字 | 被當答案 | 中 | session 吃掉所有 UNKNOWN | ✅ 已修（結束練習指令） |
| 8 | 「入庫」代替「1」| 巧合成功 | 低 | 兩個狀態意外配合 | ✅ 已修（SAVE + pending → 確認入庫） |
| 9 | 切換模式有 pending | 模式切換無確認 | **高** | _dispatch_command 缺 handler | ✅ 已修（安全指令白名單） |
| 10 | 單字元查詢 | heuristic 漏接 | 低 | 最小長度限制 2 | ✅ 已修（最小長度降至 1） |
| 11 | Emoji 輸入 | FALLBACK + 可被入庫 | 中 | heuristic 不認 emoji | ✅ 已修（內容檢查 + 引導訊息） |
| 12 | 隱形字元（ZWS） | 儲存汙染、搜尋失效 | **高** | 無 Unicode 正規化 | ✅ 已修（入口 sanitize） |
| 13 | 指令多打字「入庫了」 | 誤當學習素材 | 中 | regex 嚴格匹配無模糊提示 | ✅ 已修（近似指令偵測） |
| 14 | 純空白/純符號輸入 | 空內容可被入庫 | **高** | 無最低有效性檢查 | ✅ 已修（三層防堵） |
| 15 | 多行單字列表 | 當成單一「單字」 | 中 | `' '` 檢查不含換行 | ✅ 已修（改用 split() == 1） |
| 16 | 半形片假名 | heuristic 不認日文 | **高** | Unicode 範圍漏掉 FF65-FF9F | ✅ 已修（加入半形片假名範圍） |
| 17 | 中文誤判為日文 | 中文存為日文素材 | 中 | CJK 範圍涵蓋中日韓 | ✅ 已修（kana/CJK 拆分，純漢字降信心度） |
| 18 | 純 URL 輸入 | URL 字串存入 DB | 低 | 無 URL 偵測 | ✅ 已修（URL 偵測 + 引導訊息） |
| 19 | 快速連發（race） | 確認在 pending 前到達 | **高** | 背景 task 無 per-user 序列化 | ✅ 已修（per-user asyncio.Lock） |
| 20 | 試算表 TSV 貼上 | heuristic 全不匹配 | 中 | 混合語言稀釋比率 | ✅ 已修（Tab 偵測 → 直接入庫） |
| 21 | 全形英數字（ａｐｐｌｅ）| heuristic 不認、指令不匹配 | **高** | 無 NFKC 正規化 | ✅ 已修（NFKC 正規化） |
| 22 | 混合語言句子 | heuristic 兩邊都不匹配 | 中 | japanese_ratio 嚴格大於 0.5 | ✅ 已修（>= 0.5） |
| 23 | Romaji 輸入 | 被當多個英文單字拆開 | 中 | 無 Romaji 偵測 | ✅ 已修（Romaji 偵測） |
| 24 | 非「1」數字（"2","3"）| pending 靜默清除 | 中 | 數字無特殊處理 | ✅ 已修（數字提示） |
| 25 | 引號包裹輸入 | 引號跟著存入 DB | 低 | 未剝除成對引號 | ✅ 已修（引號剝除） |
| 26 | 超長文本（5000+字）| 截斷+高費用 | **高** | 無長度上限、Router 送全文 | ✅ 已修（超長直接入庫） |
| 27 | 非文字訊息（貼圖等）| 完全沒反應 | 中 | 靜默 return 無回覆 | ✅ 已修（回覆提示） |
| 28 | Webhook 重複送達 | 重複回覆+重複費用 | **高** | 無 event 去重機制 | ✅ 已修（event 去重） |
| 29 | 韓文 Hangul 輸入 | FALLBACK 但可被入庫 | 中 | isalpha() 認所有 Unicode 字母 | ✅ 已修（語言檢查） |
| 30 | 手機自動修正 | 查到錯誤的字 | 低 | client 端行為，無法直接修復 | ✅ 已修（UX 提示） |
