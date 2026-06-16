# GCP 蝦皮賣家百科智能助手 - 使用與運行指南 (Shopee Seller Encyclopedia Chatbot)

本專案為企業級「蝦皮賣家百科智能助手」，深度整合 **LlamaIndex**（資料處理與混合檢索）與 **LangChain / LangGraph**（對話流程代理），並提供以下兩種模組與運行模式：

1. **離線手動爬蟲更新工具 (`crawler.py`)**：手動觸發執行，用於爬取蝦皮賣家幫助中心（`https://seller.shopee.tw/edu/article`）下的文章政策，切分語意塊並生成向量資料存入 GCP BigQuery 或本地 SQLite 資料庫。手動觸發可大幅節省雲端執行與 LLM 運算成本。
2. **在線對話 Web 服務**：
   - **CLI 互動測試工具 (`app.py`)**：用來測試 RAG 檢索邏輯、混合搜尋（Hybrid Rerank）、防禦性 Prompt、賣家偏好反思等核心功能。
   - **FastAPI / LINE Chatbot Webhook 伺服器 (`main.py`)**：對接 LINE Messaging API，可透過手機 LINE 直接與 RAG 百科機器人對話，部署於 **GCP Cloud Run**。

---

## 🛠️ 環境配置與準備

在運行任何服務前，請先完成以下環境配置。

### 1. 建立 Python 3.11 虛擬環境與安裝依賴
建議使用高速 Python 套件管理工具 `uv` 或 `pip` 進行管理：
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
# 1. 核心模型設定 (本專案採用 anthropic 或 gemini 等)
MODEL_TYPE=google_gemini
GEMINI_API_KEY=您的_Gemini_API_Key
# 若使用 Claude
# MODEL_TYPE=anthropic
# ANTHROPIC_API_KEY=您的_Claude_API_Key

# 2. GCP BigQuery 設定 (若不填寫，系統會自動 fallback 採用本地 SQLite 資料庫)
BIGQUERY_PROJECT=您的_GCP_專案ID
GOOGLE_CLOUD_PROJECT=您的_GCP_專案ID
ENV=dev

# 3. LINE Bot 金鑰
LINE_CHANNEL_ACCESS_TOKEN=您的_LINE_Access_Token
LINE_CHANNEL_SECRET=您的_LINE_Channel_Secret
```

### 3. GCP 認證授權 (連線 BigQuery 必備)
若要連線至您設定完成的 GCP BigQuery，請先在本地終端機執行：
```bash
gcloud auth application-default login
```

---

## 1. 🕷️ 離線爬蟲與向量更新管線 (`crawler.py`)

用於將蝦皮賣家政策文章抓取並更新到向量資料庫中。

### 執行方式
```bash
# 抓取預設的文章 (ID: 101, 102, 103, 104) 並寫入資料庫
python crawler.py

# 指定特定的文章 ID 進行抓取更新 (以逗號分隔)
python crawler.py --ids 101,102,103,104,105
```

> [!NOTE]
> **防擋防護與 Mock 機制**：由於蝦皮官方設有 Cloudflare 等防爬蟲機制，此爬蟲模組會優先嘗試 HTTP 實時抓取；如果被平台阻擋或返回 403 錯誤，系統會自動 fallback 讀取內建的高品質賣家百科 Mock 資料（涵蓋成交手續費、賣家計分、超商免運專案、商品上架規範），確保管線能順利完成測試與資料寫入。

---

## 2. 🧪 CLI 本地問答測試工具 (`app.py`)

主要用於開發階段，快速驗證 RAG 檢索與對話代理的表現。

### 執行方式
```bash
python app.py
```

### 提供的功能與選單
啟動後會出現以下選項：
1. **測試 LlamaIndex 獨立檢索功能**：直接展示針對賣家百科進行「語意分塊 + 句子窗口 + 混合搜尋」後的檢索節點分數與上下文。
2. **測試 LangChain RAG 代理對話**：輸入預設的多輪對話測試，觀察 Agent 如何進行問題濃縮（Query Condensation）與安全驗證。
3. **進行完整互動式問答**：進入 CLI 聊天模式，您可以自由輸入關於賣家運作、出貨與手續費等規範問題。
4. **重置資料庫與重新抓取賣家百科 (Reset & Crawl)**：清空 SQLite 或 BigQuery 中的資料表，重新下載蝦皮文章並重新建立向量資料庫。
5. **退出**。

---

## 3. 💬 LINE Chatbot Webhook 伺服器 (`main.py`)

讓您能直接用手機 LINE 對話，體驗真實的賣家百科 RAG 服務。

### 本地測試步驟

#### Step 1: 啟動本地 FastAPI 伺服器
```bash
python -m uvicorn main:app --reload --port 8000
```
* 伺服器啟動時會自動加載資料庫中已有的向量節點。
* 監聽本地 `http://127.0.0.1:8000`。

#### Step 2: 使用 ngrok 開啟 HTTPS 穿透內網
由於 LINE 的 Webhook 伺服器必須使用公開的 HTTPS 網址，在另一個終端機視窗執行：
```bash
ngrok http 8000
```
這會產生一個臨時網址，例如：`https://xxxx-xx-xx.ngrok-free.app`。

#### Step 3: LINE Developers Console 設定
1. 登入 [LINE Developers Console](https://developers.line.biz/)，設定 **Webhook URL** 為：`https://xxxx-xx-xx.ngrok-free.app/webhook`。
2. 點擊 **Verify**，成功會顯示 **Success**。
3. 開啟下方 **Use webhook** 欄位開關。
4. 在官方帳號管理後台關閉 LINE 官方預設自動回覆，改為 **聊天機器人 (Chatbot)** 模式。

---

## 📂 專案結構說明
* `crawler.py`: 蝦皮賣家百科文章手動爬取與向量資料更新腳本。
* `app.py`: CLI 本地測試與展示主控台程式。
* `main.py`: FastAPI Web 伺服器（處理 LINE 傳來的 Webhook，部署至 Cloud Run）。
* `config.py`: 資料庫連線（BigQuery / SQLite）與多供應商 LLM 初始化設定。
* `ingestion.py`: LlamaIndex 文件剖析分塊、向量生成與高效寫入/讀取。
* `agent.py`: LangChain + LangGraph 對話代理圖結構實作（包含賣家偏好紀錄與安全隔離防護）。
* `schema.sql`: 本地 SQLite/BigQuery 的資料表定義。
* `tests/`: 包含對話代理與 RAG 機制的測試套件。
