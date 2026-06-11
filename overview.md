GCP 智能財報分析助手：系統架構與部署規範文件

作為 Google Cloud AI 解決方案專家，本文件旨在為企業級「智能財報分析助手」提供標準化架構藍圖。本系統深度整合 LangChain 的編排靈活性與 LlamaIndex 的資料檢索效能，並全量部署於 Google Cloud Platform (GCP) 生態系，確保生產環境的高可用性、安全性與可擴展性。


--------------------------------------------------------------------------------


1. 系統總體架構概覽 (System Architecture Overview)

本架構採用「統一封裝於單一 Cloud Run」的設計理念。將 RAG 管道（Loading, Indexing, Storing, Querying）封裝於微服務中，旨在簡化 VPC Connector 管理、降低服務間通訊延遲，並有效控制 Serverless 環境下的 Cold Start 影響。

* Loading (資料載入)：原始財報文件（PDF/Excel）存放於 Google Cloud Storage (GCS)，透過 LlamaIndex 進行異步讀取。
* Indexing (索引建構)：文件被拆解為 Nodes（LlamaIndex 的原子資料單元），進行語意分塊並生成嵌入向量。
* Storing (儲存)：使用 GCP BigQuery 作為核心後端，同時儲存分段資料、向量數據（以 JSON 陣列表示並在記憶體中還原為索引）、Metadata 以及對話歷史。開發與生產環境透過 Dataset 名稱進行隔離。
* Querying (查詢與生成)：透過 Cloud Run 上的 FastAPI 服務接收請求，執行 Agentic RAG 邏輯，並由 Vertex AI 或跨供應商模型生成回答。


--------------------------------------------------------------------------------


2. 模型抽象層：一鍵切換機制 (Multi-Model Orchestration)

系統導入 LangChain 的 initChatModel 介面，實現動態模型編排。開發者可透過環境變數無縫切換模型供應商，無需修改核心邏輯。

支援模型類型	供應商	切換參數 (MODEL_TYPE)	理想使用場景
高階推理模型	Google Gemini	google_gemini	多模態財報、複雜邏輯推理
企業級整合	Vertex AI	vertex_ai	GCP 原生合規性要求之場景
長文本分析	Anthropic	anthropic	超長篇幅年度審計報告
泛用型效能	OpenAI (GPT)	openai	標準 RAG 與快速原型開發
跨雲整合	Azure / Bedrock	azure / bedrock	跨雲端多重備援架構
本地/開源模型	Ollama	ollama	敏感數據本地化試點


--------------------------------------------------------------------------------


3. 資料載入與索引管線 (Data Ingestion & Indexing Pipeline)

本系統將文檔轉化為 Nodes，以便進行精細化管理。獨立的 Ingestion 管線可確保未來對接定期爬蟲時的模組化擴充。

1. 資料擷取 (Loading)：
  * 使用 SimpleDirectoryReader 配合 GCS 聯結器讀取財報文件。
2. 原子化處理 (Transformation to Nodes)：
  * 語意分塊 (Semantic Splitter)：使用 SemanticSplitterNodeParser（參數 breakpoint_percentile_threshold=95），確保財務數據脈絡不被機械式切斷。
  * 句子窗口 (Sentence Window)：附加 SentenceWindowNodeParser（window_size=3），在檢索時為每個 Node 提供充足的上下文，提升精準度。
3. Metadata 提取：
  * 針對 SEC 文件執行特徵提取，將「會計年度」、「季度」、「公司代碼」與「重要指標」寫入 Node 的 Metadata。
4. 獨立管線設計：
  * Ingestion 逻辑與查詢介面解耦，支持異步觸發索引更新（如接收到 GCS Object Finalized 事件時）。


--------------------------------------------------------------------------------


4. 語意記憶與狀態管理 (Conversational Memory & BigQuery)

為實現具備「長期記憶」的財務顧問體驗，系統利用 GCP BigQuery 進行狀態管理與對話歷史儲存。

* 對話狀態持久化：使用 BigQuery 連線包裝實作。每個用戶對話均受 Namespace 隔離，確保數據隱私與隔離性。
* 長期記憶與反思機制 (Reflection)：
  * 在 LangGraph 中設計異步 Reflection Node。當對話結束時，系統自動回顧對話，提取用戶偏好。
  * Profile 更新：將提取的資訊更新至儲存在 BigQuery 中的 JSON Profile。

用戶偏好 Profile (JSON 範例)：

{
  "user_namespace": "org_a_user_123",
  "investment_focus": ["Semiconductor", "Foundry Service"],
  "risk_tolerance": "Low",
  "preferred_format": "JSON with inline citations",
  "extracted_knowledge": {
    "last_reviewed_ticker": "TSM",
    "interested_metrics": ["Gross Margin", "Capex"]
  }
}



--------------------------------------------------------------------------------


5. Agentic RAG 邏輯與對話優化 (Agentic RAG & Multi-turn)

系統採用 Condense + Context 策略，並引入 QueryFusionRetriever 以優化複雜財務查詢。

1. 問題濃縮 (3-Step Sequence)：
  * Step 1: 將歷史對話與新問題交給 LLM，生成 Standalone Question (獨立查詢語句)。
  * Step 2: 使用獨立語句執行檢索。
  * Step 3: 將檢索內容 + 原始對話交給 LLM 生成最終「Grounding」回答。
2. 混合檢索 (Hybrid Search)：
  * 調用 QueryFusionRetriever 整合向量檢索與 BM25 關鍵字檢索。
  * 使用 RRF (Reciprocal Rerank Fusion) 進行結果融合，解決財務術語（如專有名詞代碼）在純向量空間中召回率不足的問題。
3. 意圖路由 (Routing)：
  * LangGraph 負責識別「一般閒聊」與「專業檢索」之路由，過濾無效查詢以降低運算成本。


--------------------------------------------------------------------------------


6. 防禦性提示詞與領域安全性 (Defensive Prompting & Security)

為應對 間接提示詞注入 (Indirect Prompt Injection)，系統在提示詞工程與生成後校驗上進行雙重防禦。

* 上下文隔離 (Delimiters)：使用 XML 標籤標記資料來源，嚴格隔離指令與資料。
* 系統指令範例：
* 生成後驗證 (Response Validation)：
  * 檢查輸出內容是否包含非預期的 JSON 結構（若非請求格式），作為識別注入成功的指標並攔截回覆。


--------------------------------------------------------------------------------


7. GCP 統一封裝與部署 (Deployment on Cloud Run)

系統封裝為 Docker 容器，利用 Cloud Run 的 Serverless 優勢，結合 Secret Manager 管理敏感金鑰。

* 部署檢查清單 (Pre-deployment Checklist)：
  * [ ] BigQuery: 已在 GCP 專案中啟用 BigQuery API，並建立對應的 Dataset (如 LLM_chatbot_dev)。
  * [ ] IAM Roles: 運行帳戶具備 roles/bigquery.admin (或 bigquery.dataEditor 暨 bigquery.user), roles/storage.objectViewer, roles/secretmanager.secretAccessor。
  * [ ] Networking: 確保 Cloud Run 服務可直接透過 API 呼叫存取 GCP BigQuery。
  * [ ] Secret Manager: 已存儲 BIGQUERY_PROJECT 與各供應商 API Keys。
  * [ ] Environment Variables: MODEL_TYPE, GCS_BUCKET_NAME, LOG_LEVEL 已正確配置。


--------------------------------------------------------------------------------


8. CI/CD 持續整合與部署流程 (CI/CD Workflow)

基於 GCP 生態系構建全自動化發佈管線，確保模型與邏輯的穩定疊代。

1. 開發階段 (Develop)：代碼提交至儲存庫，觸發 Cloud Build 進行單元測試與鏡像封裝。
2. 構建階段 (Build)：將封裝好的 Docker 鏡像推送到 Artifact Registry，並附加版本標籤 (Tag)。
3. 部署階段 (Deploy)：
  * 使用 Cloud Deploy 啟動發佈流程。
  * 支持 Canary (金絲雀發佈) 或 Blue-Green 策略，在新版本正式上線前進行流量切換與監控校驗。
  * 自動觸發 LangSmith 進行 Faithfulness (忠實度) 與 Correctness (正確性) 的離線評估。
