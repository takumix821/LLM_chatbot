# GCP 蝦皮賣家百科智能助手 - 使用與運行指南 (Shopee Seller Encyclopedia Chatbot)

本專案為企業級「蝦皮賣家百科智能助手」，深度整合 **LlamaIndex**（資料處理與混合檢索）與 **LangChain / LangGraph**（對話流程代理），並將程式碼架構重整為標準生產規格。專案提供以下模組與運行模式：

1. **離線手動爬蟲更新工具 (`crawler/crawler.py`)**：手動觸發執行，用於爬取蝦皮賣家幫助中心（`https://seller.shopee.tw/edu/article`）下的文章政策，切分語意區塊並生成向量資料存入 GCP BigQuery 或本地 SQLite 資料庫。
2. **在線對話 Web 服務**：
   - **CLI 互動測試工具 (`cli/app.py`)**：用來測試 RAG 檢索邏輯、混合搜尋（Hybrid Rerank）、防禦性 Prompt、賣家偏好反思等核心功能。
   - **FastAPI / LINE Chatbot Webhook 伺服器 (`src/main.py`)**：對接 LINE Messaging API，可透過手機 LINE 直接與 RAG 百科機器人對話，部署於 **GCP Cloud Run**。

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
# 1. 核心模型設定
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
若要連線至您設定完成的 GCP BigQuery，請先在本地終端機執行：
```bash
gcloud auth application-default login
```

---

## 1. 🕷️ 離線爬蟲與向量更新管線 (`crawler/crawler.py`)

用於將蝦皮賣家政策文章抓取並更新到向量資料庫中。

### 執行方式
```bash
# 執行模組，抓取預設的文章 (ID: 19182, 27708, 27709) 並寫入資料庫
python -m crawler.crawler

# 指定特定的文章 ID 進行抓取更新 (以逗號分隔)
python -m crawler.crawler --ids 101,102,103,104
```

> [!NOTE]
> **防擋防護與 Mock 機制**：由於蝦皮官方設有 Cloudflare 等防爬蟲機制，此爬蟲模組會優先嘗試 HTTP 實時抓取；如果被平台阻擋或返回 403 錯誤，系統會自動 fallback 讀取內建的高品質賣家百科 Mock 資料（涵蓋成交手續費、賣家計分、超商免運專案、商品上架規範），確保管線能順利完成測試與資料寫入。

---

## 2. 🧪 CLI 本地問答測試工具 (`cli/app.py`)

主要用於開發階段，快速驗證 RAG 檢索與對話代理的表現。

### 執行方式
```bash
python cli/app.py
```

### 提供的功能與選單
啟動後會出現以下選項：
1. **測試 LlamaIndex 獨立檢索功能**：展示針對賣家百科進行「語意分塊 + 句子窗口 + 混合搜尋」後的檢索節點分數與上下文。
2. **測試 LangChain RAG 代理對話**：輸入預設的多輪對話測試，觀察 Agent 如何進行問題濃縮（Query Condensation）與安全驗證。
3. **進行完整互動式問答**：進入 CLI 聊天模式，您可以自由輸入關於賣家運作、出貨與手續費等規範問題。
4. **重置資料庫與重新抓取賣家百科 (Reset & Crawl)**：清空 SQLite 或 BigQuery 中的資料表，重新下載蝦皮文章並重新建立向量資料庫。
5. **退出程式**。

---

## 3. 💬 LINE Chatbot Webhook 伺服器 (`src/main.py`)

讓您能直接用手機 LINE 對話，體驗真實的賣家百科 RAG 服務。

### 本地測試步驟

#### Step 1: 啟動本地 FastAPI 伺服器
```bash
PYTHONPATH=src python -m uvicorn main:app --reload --port 8000
```
* 伺服器啟動時會自動加載資料庫中已有的向量節點。
* 監聽本地 `http://127.0.0.1:8000`。

#### Step 2: 使用 ngrok 開啟 HTTPS 穿透內網
由於 LINE 的 Webhook 伺服器必須使用公開的 HTTPS 網址，在另一個終端機視窗執行：
```bash
ngrok http 8000
```
這會產生一個臨時網址，例如：`https://xxxx-xx-xx.ngrok-free.app`。

#### Step 3: LINE Webhook 設定
1. 登入 LINE Developers Console，設定 **Webhook URL** 為：`https://xxxx-xx-xx.ngrok-free.app/webhook`。
2. 點擊 **Verify**，成功會顯示 **Success**。
3. 開啟 **Use webhook** 欄位。

---

## 📂 專案結構說明
* `src/`: 真的要部署的對話 Web 服務程式碼
  - `main.py`: FastAPI Web 伺服器（處理 LINE 的 Webhook 訊息）。
  - `agent.py`: LangChain + LangGraph 對話代理圖結構。
  - `config.py`: 資料庫（BigQuery / SQLite）與 LLM / Embedding 初始化。
  - `ingestion.py`: LlamaIndex 文件剖析、向量生成與資料庫讀寫。
  - `schema.sql`: 資料庫資料表定義定義檔。
* `crawler/`: 離線文章爬取與向量更新管線
  - `crawler.py`: 爬蟲主程式（在雲端部署為 **Cloud Run Job**）。
  - `Dockerfile.crawler`: 爬蟲 Job 的容器設定檔。
* `cli/`: 本地問答與獨立測試控台
  - `app.py`: CLI 互動測試選單主程式。
* `docs/`: 統一存放的系統文檔
  - `architecture.md`: 系統架構設計與 RRF 檢索圖。
  - `overview.md`: 雲端 GCP 資源配置概述。
  - `doc.md`: 技術規格細節文件。
* `Dockerfile`: 對話 Web 服務的生產級容器設定檔。
* `.github/workflows/deploy.yml`: GitHub Actions 自動編譯與 Cloud Run 部署腳本。
* `requirements.txt`: 專案相依套件清單。
* `tests/`: 單元測試套件。

