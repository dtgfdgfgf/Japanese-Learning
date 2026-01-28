# 部署指南

本文件說明如何將 LINE 日語學習助教 Bot 部署到生產環境。

## 目錄

- [Prerequisites](#prerequisites)
- [Railway 部署](#railway-部署)
- [Render 部署](#render-部署)
- [Docker 部署](#docker-部署)
- [環境變數設定](#環境變數設定)
- [LINE Webhook 設定](#line-webhook-設定)
- [Troubleshooting](#troubleshooting)

## Prerequisites

1. **Supabase 專案**
   - 建立 Supabase 專案取得 PostgreSQL 連線字串
   - 連線字串格式：`postgresql://[user]:[password]@[host]:[port]/[database]`

2. **LINE Messaging API Channel**
   - 前往 [LINE Developers Console](https://developers.line.biz/)
   - 建立 Messaging API Channel
   - 取得 Channel Secret 和 Channel Access Token

3. **LLM API Keys**
   - Anthropic API Key (主要)
   - OpenAI API Key (備援)

## Railway 部署

### 步驟

1. **建立 Railway 帳號**
   - 前往 [Railway](https://railway.app/)
   - 使用 GitHub 登入

2. **建立新專案**
   - 點擊 "New Project"
   - 選擇 "Deploy from GitHub repo"
   - 選擇你的 repository

3. **設定環境變數**
   在 Variables 頁面新增以下變數：
   ```
   DATABASE_URL=postgresql+asyncpg://...
   LINE_CHANNEL_SECRET=...
   LINE_CHANNEL_ACCESS_TOKEN=...
   ANTHROPIC_API_KEY=...
   OPENAI_API_KEY=...
   USER_ID_SALT=...
   ```

4. **設定 Start Command**
   ```
   uvicorn src.main:app --host 0.0.0.0 --port $PORT
   ```

5. **部署**
   - Railway 會自動建置並部署
   - 取得部署 URL (例如: `https://your-app.up.railway.app`)

6. **執行資料庫遷移**
   - 在 Railway 專案中開啟 Terminal
   - 執行 `alembic upgrade head`

## Render 部署

### 步驟

1. **建立 Render 帳號**
   - 前往 [Render](https://render.com/)
   - 使用 GitHub 登入

2. **建立 Web Service**
   - 點擊 "New" → "Web Service"
   - 連接你的 GitHub repository

3. **設定服務**
   - **Name**: japanese-learning-bot
   - **Environment**: Python 3
   - **Build Command**: `pip install -e .`
   - **Start Command**: `uvicorn src.main:app --host 0.0.0.0 --port $PORT`

4. **設定環境變數**
   在 Environment 頁面新增：
   ```
   DATABASE_URL=postgresql+asyncpg://...
   LINE_CHANNEL_SECRET=...
   LINE_CHANNEL_ACCESS_TOKEN=...
   ANTHROPIC_API_KEY=...
   OPENAI_API_KEY=...
   USER_ID_SALT=...
   ```

5. **部署**
   - 點擊 "Create Web Service"
   - 等待建置完成
   - 取得部署 URL

## Docker 部署

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY pyproject.toml .
COPY requirements.txt .
RUN pip install --no-cache-dir -e .

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 建置與執行

```bash
# 建置 image
docker build -t japanese-learning .

# 執行 container
docker run -d \
  -p 8000:8000 \
  -e DATABASE_URL=postgresql+asyncpg://... \
  -e LINE_CHANNEL_SECRET=... \
  -e LINE_CHANNEL_ACCESS_TOKEN=... \
  -e ANTHROPIC_API_KEY=... \
  -e OPENAI_API_KEY=... \
  -e USER_ID_SALT=... \
  japanese-learning
```

### Docker Compose (本地開發)

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/japanese_learning
      - LINE_CHANNEL_SECRET=${LINE_CHANNEL_SECRET}
      - LINE_CHANNEL_ACCESS_TOKEN=${LINE_CHANNEL_ACCESS_TOKEN}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - USER_ID_SALT=${USER_ID_SALT}
    depends_on:
      - db

  db:
    image: postgres:15
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_DB=japanese_learning
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

volumes:
  postgres_data:
```

## 環境變數設定

| 變數 | 說明 | 必要 |
|------|------|------|
| `DATABASE_URL` | PostgreSQL 連線字串 (asyncpg) | ✅ |
| `LINE_CHANNEL_SECRET` | LINE Channel Secret | ✅ |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Access Token | ✅ |
| `ANTHROPIC_API_KEY` | Anthropic API Key | ✅ |
| `OPENAI_API_KEY` | OpenAI API Key | ✅ |
| `USER_ID_SALT` | User ID 雜湊用 salt | ✅ |
| `DEBUG` | 除錯模式 (true/false) | ❌ |
| `LOG_LEVEL` | 日誌等級 (INFO/DEBUG/ERROR) | ❌ |

### 安全注意事項

- **絕對不要** 在程式碼中 hardcode secrets
- 使用雲端服務的 Secret Management
- 定期更換 API keys
- 使用強隨機字串作為 `USER_ID_SALT`

## LINE Webhook 設定

1. **取得部署 URL**
   - Railway: `https://your-app.up.railway.app`
   - Render: `https://your-app.onrender.com`

2. **設定 Webhook URL**
   - 前往 LINE Developers Console
   - 選擇你的 Channel
   - 前往 Messaging API 頁面
   - 設定 Webhook URL: `https://your-domain.com/webhook`

3. **啟用 Webhook**
   - 開啟 "Use webhook"
   - 關閉 "Auto-reply messages"
   - 關閉 "Greeting messages"

4. **驗證 Webhook**
   - 點擊 "Verify" 按鈕
   - 應該顯示 "Success"

## Troubleshooting

### Webhook 驗證失敗

**問題**: LINE Webhook 驗證返回錯誤

**解決方案**:
1. 確認服務已正常運行
2. 檢查 `/health` endpoint 是否回應
3. 確認 `LINE_CHANNEL_SECRET` 正確設定
4. 檢查 logs 查看錯誤訊息

### 資料庫連線失敗

**問題**: 應用程式無法連接資料庫

**解決方案**:
1. 確認 `DATABASE_URL` 格式正確
2. 確認使用 `postgresql+asyncpg://` scheme
3. 檢查 Supabase 連線池限制
4. 確認 IP whitelist 設定

### LLM 回應超時

**問題**: AI 分析或練習功能超時

**解決方案**:
1. 系統會自動 fallback 到 OpenAI
2. 檢查 API keys 是否有效
3. 檢查 API 配額是否用完
4. 考慮增加 timeout 設定

### 常見錯誤碼

| 錯誤碼 | 說明 | 解決方案 |
|--------|------|----------|
| 400 | Invalid signature | 檢查 LINE_CHANNEL_SECRET |
| 500 | Internal server error | 查看應用程式 logs |
| 503 | Service unavailable | 檢查資料庫連線 |

## 監控

建議設定以下監控：

1. **Health Check**
   - 監控 `/health` endpoint
   - 設定 uptime monitoring (UptimeRobot, Pingdom)

2. **Logs**
   - 使用 Railway/Render 內建 logs
   - 或整合 Sentry 進行錯誤追蹤

3. **Performance**
   - 監控回應時間
   - 設定 P95 < 3s 警報
