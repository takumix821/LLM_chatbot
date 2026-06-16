GCP 蝦皮賣家百科智能助手：系統架構與部署規範文件 (Overview & Deployment Guide)

本文件為 GCP Cloud AI 解決方案專家與架構師專用，詳細規範「蝦皮賣家百科智能助手」在 Google Cloud Platform (GCP) 的企業級標準化架構部署指南。系統利用 Cloud Run、BigQuery、Secret Manager 等原生服務，提供高可用、安全且符合預算效益（Cost-Efficient）的 RAG 解決方案。

--------------------------------------------------------------------------------

1. 系統總體架構概覽 (System Architecture Overview)

本系統採離在線分離架構，以達到最大的成本控制與維運彈性：

* 離線爬蟲 updating pipeline (GCP Job/VM)：
  - 使用者手動觸發部署於 GCP 上的 `crawler.py`。
  - 爬蟲模組從蝦皮幫助中心爬取最新文章（遇到 Cloudflare 擋爬則自動 fallback 載入 Mock 數據庫），將格式化後的文字檔儲存於 `mock_data/`。
  - 觸發 LlamaIndex 進行語意分塊與 Embedding 生成。
  - 將向量數據、Metadata 以及原始內容寫入 **GCP BigQuery** 的 `segmented_nodes` 資料表中。
* 在線對話 serving pipeline (GCP Cloud Run)：
  - FastAPI 伺服器封裝於 Docker 容器中，部署於 Cloud Run 上以享用 Serverless 的自動彈性伸縮。
  - 當收到來自手機 LINE 的對話請求，服務會連線至 BigQuery 還原向量索引，並使用 LangGraph 對話狀態流進行 RAG 合成回答。

--------------------------------------------------------------------------------

2. 模型抽象層：一鍵切換機制 (Multi-Model Orchestration)

系統使用 LangChain 的 `initChatModel` 介面，支持動態模型切換，開發者可隨時切換模型供應商以因應不同的效能與成本考量。

支援模型類型 | 供應商 | 切換參數 (MODEL_TYPE) | 理想使用場景
--- | --- | --- | ---
高效智能推論 | Google Gemini | google_gemini | 預設模型，Gemini-1.5-Flash 推理快速且成本極低
企業級整合 | Vertex AI | vertex_ai | GCP 原生合規性要求之場景
長文本分析 | Anthropic | anthropic | 處理大量複雜賣家長篇文章規章
標準型效能 | OpenAI (GPT) | openai | 標準 RAG 與快速原型開發
本地開源模型 | Ollama | ollama | 敏感數據本地化測試

--------------------------------------------------------------------------------

3. 資料載入與索引管線 (Data Ingestion & Indexing Pipeline)

本系統與單一文件讀取不同，特別為爬蟲產出的結構化文字進行了欄位化解析：

1. 資料擷取 (Loading)：
   - `crawler.py` 會將抓取到的文章以帶有 Metadata 標頭（Article URL, Article Title, Category, Sub-Category）的結構化純文字檔存入 `mock_data/`。
2. 剖析與標註 (Transformation to Nodes)：
   - 語意分塊：`SemanticSplitterNodeParser`（breakpoint_percentile_threshold=95）依據主題段落進行分塊。
   - 句子窗口：`SentenceWindowNodeParser`（window_size=3）在檢索時能提供精確句子，而在 LLM 推理時還原前後句。
   - 蝦皮 Metadata 提取：`extract_shopee_article_metadata` 自動解析文章標題、網址與大分類，並依內容掃描標註 `手續費/費用`、`計分/違規` 等標籤。

--------------------------------------------------------------------------------

4. 語意記憶與狀態管理 (Conversational Memory & BigQuery)

為了提供具備「長期記憶與偏好適配」的賣家顧問體驗，系統利用 GCP BigQuery 儲存賣家對話狀態與 Profile。

* 對話狀態持久化：使用 BigQuery 連線包裝。對話歷史依 LINE user_id 進行實體隔離。
* 賣家偏好反思機制 (Reflection)：
  - 採用 LangGraph 異步 Reflection Node，在對話結束後總結賣家詢問的主題（手續費、出貨、罰分等）並寫入 JSON Profile。

賣家偏好 Profile (JSON 範例)：
```json
{
  "user_namespace": "Ua7812f8310c9d92e...",
  "shop_category": ["服飾配件", "美妝個清"],
  "experience_level": "New",
  "preferred_format": "條列式說明搭配重點標記",
  "extracted_knowledge": {
    "last_reviewed_topic": "成交手續費",
    "interested_policies": ["手續費費率", "出貨延遲規範"]
  }
}
```

--------------------------------------------------------------------------------

5. Agentic RAG 邏輯與對話優化

* 問題濃縮 (Query Condensing)：將多輪對話歷史與新輸入問題進行融合成獨立查詢句，防止 RAG 在指代名詞（如「那這個要多少錢？」）時檢索失準。
* 混合檢索 (Hybrid Search & RRF)：融合 Vector 語意檢索與 BM25 關鍵字檢索，有效解決賣家特定政策術語（如「洗版」、「重複刊登」、「OK超商運費」）在向量空間中的召回率不足問題。
* 意圖路由 (Intent Router)：快速過濾一般閒聊，省下檢索開銷。

--------------------------------------------------------------------------------

6. 部署檢查清單 (GCP Pre-deployment Checklist)

* [ ] **BigQuery**: 已在 GCP 專案中啟用 BigQuery API，並建立對應的 Dataset (如 `LLM_chatbot_dev` 與 `LLM_chatbot_prod`)。
* [ ] **IAM 權限**: 運行帳戶具備 `roles/bigquery.admin`（或 BQ 資料寫入/讀取權限）、`roles/secretmanager.secretAccessor`。
* [ ] **Secret Manager**: 已將敏感的金鑰（如 `GEMINI_API_KEY`, `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_CHANNEL_SECRET`）以密鑰形式存儲於 GCP Secret Manager。
* [ ] **環境變數**: Cloud Run 啟動引數已配置 `MODEL_TYPE`、`BIGQUERY_PROJECT`、`ENV=prod`。
