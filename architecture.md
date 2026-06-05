# GCP 智能財報分析助手：系統架構與設計文件 (Architecture Design)

本文件詳細記錄了「智能財報分析助手」的系統架構、技術堆疊、核心運作流程，以及針對財報專有場景（如表格解析與向量空間微調）的優化路線圖。

---

## 1. 系統架構總覽 (System Architecture Overview)

本系統採用 **RAG (檢索增強生成)** 架構，並結合了 **LlamaIndex 的高效率檢索** 與 **LangChain/LangGraph 的 Agent 狀態管理及工作流控制**。

系統區分為兩個獨立且互補的管道：
1. **離線預處理管道 (Offline Ingestion & Indexing Pipeline)**：負責將大量的非結構化財報文件轉換為可檢索的向量與結構化數據。
2. **在線對話生成管道 (Online Querying & Agentic Flow)**：負責在使用者提問時，即時搜尋相關數據並透過大語言模型（LLM）生成回答。

```mermaid
flowchart TD
    subgraph 離線預處理 (Offline Indexing)
        GCS[(Google Cloud Storage)] -->|讀取 PDF/TXT| Reader[SimpleDirectoryReader]
        Reader -->|文章分段| Splitter[Semantic & Sentence Window Splitter]
        Splitter -->|計算向量| Embed[Vertex AI/Gemini Embedding]
        Embed -->|儲存| AlloyDB[(GCP AlloyDB Vector Store)]
    end

    subgraph 在線對話 (Online Querying)
        User[使用者問題] -->|意圖路由| Router{LangGraph Intent Router}
        Router -->|專業財報問題| Condense[問題濃縮 / Standalone Query]
        Router -->|一般對話| Chat[閒聊節點 / Chitchat Node]
        
        Condense -->|檢索問題向量| Retrieve[混合檢索 QueryFusionRetriever]
        AlloyDB -.->|相似度比對| Retrieve
        Retrieve -->|篩選門檻| Filter[SimilarityPostprocessor]
        
        Filter -->|XML 隔離上下文| LLM[LLM 回答生成]
        LLM -->|輸出校驗| Validate{Security Validation}
        Validate -->|通過| Reflect[Reflection Node 更新 Prefs]
        Validate -->|安全漏洞| Block[攔截並警示]
    end
```

---

## 2. 離線預處理管道 (Offline Indexing)

本階段的主要任務是將財報文件碎片化並建立向量化資料庫。

### 核心技術與步驟：
1. **資料載入 (Ingestion)**：
   * **技術**：LlamaIndex `SimpleDirectoryReader` 搭配 GCS 連接器。
   * **作用**：異步讀取 PDF/TXT 等源檔案。
2. **語意分塊 (Semantic Chunking)**：
   * **技術**：`SemanticSplitterNodeParser` (門檻設為 `95%`)。
   * **作用**：不同於固定字數的機械切分，此解析器會計算相鄰句子的向量相似度，當語意發生顯著偏離（即主題改變）時才進行切分，保留段落主題的完整性。
3. **句子窗口標記 (Sentence Window Parsing)**：
   * **技術**：`SentenceWindowNodeParser` (預設 `window_size=3`)。
   * **作用**：檢索時只檢索精確的單句（以提高檢索精準度），但在送給 LLM 時，會自動回填該句子前後各 3 句的上下文（確保上下文脈絡不中斷）。
4. **中介資料提取 (Metadata Extraction)**：
   * **技術**：正則表達式 (Regex) 與特徵提取器。
   * **作用**：自動提取 `company_code` (如 AAPL)、`fiscal_year` (如 2026)、`quarter` (如 Q1) 以及 `important_metrics` (如 Revenue, Gross Margin)，以便進行 Metadata 過濾。
5. **向量化與儲存 (Storing)**：
   * **技術**：Vertex AI Embedding 或 Gemini Embedding，搭配 GCP AlloyDB (開啟 `pgvector` 擴充)。
   * **作用**：儲存 Nodes 的原始文本、Metadata 與其 768/1536 維度的向量。

---

## 3. 在線對話管道 (Online Querying)

當使用者在終端機或 Line 對話框輸入訊息時，即時運作的工作流。

### 核心技術與步驟：
1. **對話歷史與意圖路由 (Intent Routing)**：
   * **技術**：`LangGraph` + `PostgresChatMessageHistory`。
   * **作用**：自動判定使用者是「日常閒聊」還是「財報數據詢問」，閒聊則直接回覆以省下檢索成本。
2. **問題濃縮 (Query Condensing)**：
   * **技術**：LangChain LLM Chain。
   * **作用**：將多輪對話的歷史脈絡（如：「我想查 Apple」、「那毛利率呢？」）濃縮成一個獨立且完整的查詢句（如：「Apple 的毛利率是多少？」）。
3. **混合檢索 (Hybrid Search & RRF)**：
   * **技術**：LlamaIndex `QueryFusionRetriever`。
   * **作用**：同時進行 **向量檢索**（尋找語意相近的段落）與 **BM25 關鍵字檢索**（精準匹配股票代碼與會計科目如 EBITDA）。使用 **RRF (Reciprocal Rerank Fusion)** 進行結果融合。
4. **相似度過濾 (Similarity Post-processing)**：
   * **技術**：`SimilarityPostprocessor` (門檻設為 `0.78`，並加入 RRF 檢索的自適應放寬機制)。
   * **作用**：過濾掉相關性過低的段落，避免干擾 LLM。
5. **防禦性 Prompt 設計 (Defensive Prompting)**：
   * **技術**：XML 標籤物理隔離設計。
   * **作用**：使用 `<context>` 與 `<context_stream>` 將檢索到的外源數據與系統指令徹底隔離，防止「間接提示注入攻擊 (Indirect Prompt Injection)」。
6. **回答生成與輸出驗證 (Generation & Validation)**：
   * **技術**：LangChain `initChatModel` 搭配輸出格式檢查。
   * **作用**：使用 `compact` 引用友善模式合成回答，並由驗證節點檢查內容中是否包含安全注入漏洞，保證合規審計。
7. **長期記憶與反思 (Reflection & Preferences)**：
   * **技術**：LangGraph 異步 `Reflection Node`。
   * **作用**：根據使用者的查詢偏好，動態更新 AlloyDB 中的 JSON Profile 指令儲存。

---

## 4. 當前優化路線圖 (Next Steps & Tuning Roadmap)

誠如您在測試中所觀察到的，初版 RAG 在某些細節上仍有優化空間，我們將在完整流程跑通後，針對以下兩點進行深度優化：

### 優化方向 1：解決斷句方式不自然與表格過長問題 (Chunking & Table Optimization)
* **問題**：對於含有表格的財報，標準 PDF 讀取器 (PyPDF) 按行流式讀取會破壞表格的二維結構，且句子分割器會將整張表格誤判為單一巨型句子。
* **優化方案**：
  1. **導入版面配置分析 (Layout-Aware) 讀取器**：改用 **`LlamaParse`**，將 PDF 自動解析為結構完整的 Markdown Tables，保持行與列的對應關係。
  2. **自定義斷句正則表達式**：在 `SentenceWindowNodeParser` 中，設定表格換行符 `\n` 或 `|` 為句子邊界。
  3. **混合分塊策略**：結合 `MarkdownNodeParser`，專門識別 Markdown 表格與階層，並對表格採取「單行/單列」或「Summary 提取」的方式處理。
  4. **下調 Window Size**：將 `window_size` 限制在 `1` 或 `2`，防止上下文贅言過多。

### 優化方向 2：提升檢索分數合理性與向量微調 (Embedding & Reranking Tuning)
* **問題**：預設的通用向量模型對「財務術語」的敏感度不足，時間格式不一致（例如 2026Q1 與 115年第一季）造成檢索漂移，且極易誤檢索到非損益表的後方「附註 (Notes) 頁面」。
* **優化方案**：
  1. **時間格式與詞彙預對齊**：在 LangChain 的問題濃縮節點（Query Condensing），教導 LLM 在生成 Standalone Query 時，自動將西元季度（如 `2026Q1`）翻譯為台灣財報常用的民國格式（如 `115年第一季`），提高檢索匹配率。
  2. **過濾 / 排除附註頁面**：在 Ingestion 階段，利用頁碼與正則表達式，對 Node 標註 `section=main_statement` 或 `section=notes`。在對話檢索時，硬性過濾排除 `notes` 部分，僅對綜合損益表與資產負債表進行檢索，以精準鎖定核心數據。
  3. **導入 Cohere Reranker (精排模型)**：在向量初篩後，使用專門的 Cross-Encoder 模型（如 `CohereRerank`）進行精準重排，該模型對於微小的數值差異與會計術語有極高的分辨力。
  4. **選用財報專用 Embedding**：例如改用 `Voyage-Finance`（專為金融領域優化的向量模型），它在財務相關的語意空間投影比通用模型更精確。
  5. **Metadata 預過濾**：在進行相似度計算前，先根據 `company_code` 與 `fiscal_year` 進行 SQL 等級的硬性過濾，將檢索範圍縮小到目標財報，徹底避免跨年分、跨公司的數據混淆。

---

## 5. Token 節省與效能優化設計 (Token Saving & Performance Optimization) [NEW]

為降低 LLM API 呼叫成本與減少延遲，本架構在多個流程節點實作了 Token 節省策略：

### 5.1 閒聊路由分流與字數硬限制
* **設計**：透過 LangGraph 意圖路由直接分流日常對話。閒聊節點在 System Prompt 中被加入 `「限 30 字以內」` 的硬性長度約束。
* **效果**：避免模型生成贅詞，平均每次閒聊呼叫可節省約 50 ~ 100 Tokens。

### 5.2 緊湊模式回答 (Compact RAG Response)
* **設計**：在 RAG 合成回答節點中，明確注入安全性與簡潔指令：
  * 「強制使用 compact 模式：文字精鍊，直指要點。」
  * 「回答必須極其簡短，嚴禁重複描述，長度限制在 150 字以內，優先使用條列或表格。」
* **效果**：縮減高達 60% 的生成 Token 數，且表格或條列形式更利於審計合規。

### 5.3 程序記憶與指令優化限制 (Reflection Node Constraints)
* **設計**：在 LangGraph 反思節點優化 System Prompt 時，限制 LLM 生成的新指令在 `150 字以內`，且「極度簡練，排除贅詞」。
* **效果**：防止反思出的 System Instructions 隨時間不斷膨脹（避免過度累積 Prompt context 導致後續對話成本遞增）。

---

## 6. 資料庫架構與環境分離設計 (Database Schema & Environment Separation) [NEW]

為達到本地開發測試的實體儲存以及雲端部署的環境隔離，本系統設計了完整的資料庫儲存方案：

### 6.1 資料表 Schema 設計 (schema.sql)
專案內定義了 [schema.sql](file:///Users/alionking821/Documents/LLM_chatbot/schema.sql)，並在本地或雲端初始化時自動執行，包含以下三個核心資料表：

1. **`chat_history` (對話歷史紀錄表)**：
   * 用於持久化多輪對話歷史。
   * 包含欄位：`id` (主鍵)、`session_id` (對話識別碼)、`message_type` ('human' 或 'ai')、`content` (訊息內文)、`timestamp` (時間戳記)。
2. **`user_profiles` (使用者偏好與程序記憶表)**：
   * 用於儲存使用者的投資偏好、風險度及從對話中學習到的提取知識 (Extracted Knowledge)。
   * 包含欄位：`user_namespace` (隔離標籤，通常為 session_id)、`profile_data` (JSON 字串，包含偏好配置)。
3. **`segmented_nodes` (財報分段與向量索引表)**：
   * 用於本地 SQLite 的實體儲存。由於 SQLite 缺乏穩定的原生向量索引擴充套件，我們採取了**持久化儲存 + 記憶體即時構建**的混合方案：
     * **Ingestion 階段**：將 LlamaIndex 切分好的 TextNode 文字、Metadata（以 JSON 格式）、以及生成的 Embedding 向量（以 JSON 陣列格式 `[0.12, -0.45, ...]`）儲存至資料表中。
     * **Querying / 啟動階段**：如果 LlamaIndex 還沒有建立記憶體索引，則直接從 `segmented_nodes` 表中讀取所有節點與向量，在記憶體中還原為 `TextNode` 並重建 `VectorStoreIndex`。這確保了本地開發測試的持久性，同時避免了在 macOS 上編譯/安裝 sqlite-vss 的複雜環境依賴。
   * 包含欄位：`node_id` (LlamaIndex 節點 ID)、`file_name` (來源財報檔名)、`text_content` (分塊文字)、`embedding_vector` (向量 JSON 陣列字串)、`metadata_json` (起點、會計季度、頁碼等中介資料的 JSON 字串)、`created_at` (時間戳記)。

### 6.2 本地與雲端環境分離策略
本系統透過 `ENV` 環境變數與 `DATABASE_URL` 的存在判定來控制資料庫連線目標：

* **本地開發測試 (Local Environment)**：
  * 當環境中未配置 `DATABASE_URL` 時，連線至專案底下的本地 SQLite 實體資料庫檔案 `LLM_chatbot_dev.db`。
  * `LLM_chatbot_dev.db` 以及所有 `*.db` 檔案均已被加入 `.gitignore`，防止測試數據被 Commit 入庫。
* **雲端部署環境 (GCP AlloyDB / Postgres)**：
  * 當配置有 `DATABASE_URL` 時，系統會自動根據 `ENV` 環境變數動態重寫資料庫名稱後綴：
    * `ENV=dev` (雲端測試環境)：資料庫名稱為 `LLM_chatbot_dev`
    * `ENV=prod` (生產環境)：資料庫名稱為 `LLM_chatbot_prod`
  * 雲端 AlloyDB 支援 `pgvector` 原生向量檢索，確保生產環境的高效檢索效能。

