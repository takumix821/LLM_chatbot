# GCP 智能財報分析助手 - 使用與運行指南

本專案為企業級「智能財報分析助手」，深度整合 **LlamaIndex**（資料處理與混合檢索）與 **LangChain / LangGraph**（對話流程代理），並提供以下兩種運行/測試模式：

1. **CLI 互動測試工具 (`app.py`)**：用來測試語言模型 RAG 檢索邏輯、混合搜尋（Hybrid Rerank）、防禦性 Prompt、記憶更新等核心功能。
2. **LINE Chatbot Webhook 伺服器 (`main.py`)**：對接 LINE Messaging API，可透過手機 LINE 直接與 RAG 機器人對話。

---

## 🛠️ 環境配置與準備

在運行任何服務前，請先完成以下環境配置。

### 1. 建立 Python 3.11 虛擬環境與安裝依賴
建議使用高速 Python 套件管理工具 `uv` 進行管理：
```bash
# 建立 3.11 虛擬環境
uv venv --python 3.11

# 啟用環境 (Mac/Linux)
source .venv/bin/activate

# 安裝相依套件
uv pip install -r requirements.txt
```

### 2. 設定環境變數 (`.env`)
複製 `.env.example` 並重新命名為 `.env`，填入您的金鑰：
```properties
# 1. 核心模型設定 (本專案採用 anthropic)
MODEL_TYPE=anthropic
ANTHROPIC_API_KEY=您的_Claude_API_Key

# 2. GCP BigQuery 設定 (若不填寫，系統會自動 fallback 採用本地 SQLite 資料庫)
BIGQUERY_PROJECT=您的_GCP_專案ID
GOOGLE_CLOUD_PROJECT=您的_GCP_專案ID
ENV=dev

# 3. LINE Bot 金鑰
LINE_CHANNEL_ACCESS_TOKEN=您的_LINE_Access_Token
LINE_CHANNEL_SECRET=您的_LINE_Channel_Secret
```

### 3. GCP 認證授權 (連線 BigQuery 必備)
若要連線至您付費設定完成的 GCP BigQuery，請先在本地終端機執行：
```bash
gcloud auth application-default login
```

---

## 1. 🧪 CLI 測試工具 (`app.py`)

主要用於開發階段，快速驗證 RAG 檢索與對話代理的表現。

### 執行方式
```bash
./.venv/bin/python app.py
```

### 提供的功能與選單
啟動後會出現以下選項：
1. **測試 LlamaIndex 獨立檢索功能**：直接展示針對財報進行「語意分塊 + 句子窗口 + 混合搜尋」後的檢索節點分數與上下文。
2. **測試 LangChain RAG 代理對話**：輸入預設的多輪對話測試，觀察 Agent 如何進行問題濃縮（Query Condensation）與安全驗證。
3. **進行完整互動式問答**：進入 CLI 聊天模式，您可以自由輸入關於財報的問題。
4. **重置資料庫並重新解析財報**：清空 SQLite 或 BigQuery 中的資料表，重新解析 `mock_data/` 下的文件並上傳最新的向量與節點（BigQuery 上傳已實作高效串流批次寫入，2 秒內即可完成）。
5. **退出**。

---

## 2. 💬 LINE Chatbot Webhook 伺服器 (`main.py`)

讓您能直接用手機 LINE 對話，體驗真實的 RAG 服務。

### 運行步驟

#### Step 1: 啟動本地 FastAPI 伺服器
```bash
./.venv/bin/python -m uvicorn main:app --reload --port 8000
```
* 伺服器啟動時會自動加載 `mock_data/` 的財報資料並初始化索引（若資料庫中已有快取節點，則直接自資料庫載入）。
* 監聽本地 `http://127.0.0.1:8000`。

#### Step 2: 使用 ngrok 開啟 HTTPS 穿透內網
由於 LINE 的 Webhook 伺服器必須使用公開的 HTTPS 網址，在另一個終端機視窗執行：
```bash
ngrok http 8000
```
這會產生一個臨時網址，例如：`https://xxxx-xx-xx.ngrok-free.app`。

#### Step 3: LINE Developers Console 設定
1. 登入 [LINE Developers Console](https://developers.line.biz/)，點進您的 Messaging API Channel。
2. 在 **Messaging API settings** 中設定 **Webhook URL** 為：`https://xxxx-xx-xx.ngrok-free.app/webhook`（注意要加上 `/webhook` 後綴）。
3. 點擊 **Verify**，成功會顯示 **Success**。
4. 開啟下方 **Use webhook** 欄位開關。

#### Step 4: 關閉 LINE 預設自動回覆（非常重要）
1. 在同一個設定頁面，拉到 **LINE Official Account features**。
2. 點擊 **Auto-reply messages** 右方的 **Edit**，會跳轉至 LINE 官方帳號管理後台。
3. 在回應設定頁面中：
   * **回應模式**：設定為 **聊天機器人 (Chatbot)**。
   * **Webhook**：設定為 **啟用 (Enabled)**。
   * **自動回應訊息**：設定為 **停用 (Disabled)**。

#### Step 5: 掃碼加好友並對話
回到 LINE Developers **Messaging API settings** 頁面，使用手機 LINE 掃描下方 QR Code 加入好友，即可開始向機器人提問財報問題！

---

## 📂 專案結構說明
* `app.py`: CLI 本地測試與展示主控台程式。
* `main.py`: FastAPI Web 伺服器（處理 LINE 傳來的 Webhook）。
* `config.py`: 資料庫連線（BigQuery / SQLite）與多供應商 LLM 初始化設定。
* `ingestion.py`: LlamaIndex 文件讀取、剖析分塊、向量生成與高效寫入/讀取。
* `agent.py`: LangChain + LangGraph 對話代理圖結構實作。
* `schema.sql`: 本地 SQLite/BigQuery 的資料表定義。
* `tests/`: 包含對話代理與 RAG 機制的測試套件。
