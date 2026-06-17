# 蝦皮賣家百科智能助手：系統架構與設計文件 (Architecture Design)

本文件詳細記錄了「蝦皮賣家百科智能助手」的系統架構、技術堆疊、核心運作流程，以及針對電商平台政策頻繁變動（如成交費率調升、違規計分新制）與計算服務費等專有場景的優化路線圖。

---

## 1. 系統架構總覽 (System Architecture Overview)

本系統採用 **RAG (檢索增強生成)** 架構，並結合了 **LlamaIndex 的高效率檢索** 與 **LangChain/LangGraph 的 Agent 狀態管理及工作流控制**。

系統區分為兩個獨立且互補的管道：
1. **離線手動爬蟲與預處理管道 (Offline Ingestion & Indexing Pipeline)**：負責定期或手動在 GCP VM/Job 觸發 `crawler.py`，爬取蝦皮賣家中心文章並寫入向量與結構化數據至資料庫，以此大幅省下昂貴的自動定時掃描成本。
2. **在線對話生成管道 (Online Querying & Agentic Flow)**：負責在賣家提問時（透過 LINE 或 CLI），即時檢索政策庫並透過大語言模型（LLM）生成回答。

```mermaid
flowchart TD
    subgraph 離線爬蟲與寫入 (Offline Manual Indexing)
        Trigger[手動觸發 Job / VM] -->|執行 crawler.py| Scraper{蝦皮爬蟲邏輯}
        Scraper -->|實時 HTTP 抓取| Live[蝦皮幫助中心官網]
        Scraper -->|被擋 Fallback| Mock[內建賣家百科 Mock 資料]
        Live -->|下載為文字檔| TextFiles[mock_data/*.txt]
        Mock -->|寫入文字檔| TextFiles
        TextFiles -->|讀取與 metadata 標註| Reader[SimpleDirectoryReader]
        Reader -->|文章分段| Splitter[Semantic & Sentence Window Splitter]
        Splitter -->|計算向量| Embed[Vertex AI/Gemini Embedding]
        Embed -->|資料寫入| BigQuery[(GCP BigQuery / SQLite)]
    end

    subgraph 在線對話與檢索 (Online LINE Chatbot)
        User[賣家問題: 運費/手續費] -->|意圖路由| Router{LangGraph Intent Router}
        Router -->|賣場經營與費率政策| Condense[問題濃縮 / Standalone Query]
        Router -->|日常對話/招呼| Chat[閒聊節點 / Chitchat Node]
        
        Condense -->|檢索問題向量| Retrieve[混合檢索 QueryFusionRetriever]
        BigQuery -.->|相似度比對| Retrieve
        Retrieve -->|篩選門檻| Filter[SimilarityPostprocessor]
        
        Filter -->|XML 隔離上下文| LLM[LLM 回答生成]
        LLM -->|輸出校驗| Validate{Security Validation}
        Validate -->|通過| Reflect[Reflection Node 更新賣家偏好]
        Validate -->|安全漏洞| Block[攔截並警示]
    end
```

---

## 2. 離線預處理與爬蟲管道 (Offline Indexing)

本階段的主要任務是抓取賣家百科文章並將其碎片化建立向量化資料庫。

### 核心技術與步驟：
1. **資料爬取 (Crawling)**：
   - 使用 `crawler.py` 運行，包含 Live 實時獲取和 Mock 高品質備份機制，以防止被蝦皮的反爬蟲機制（如 Cloudflare）完全阻斷。
   - 將文章格式化輸出為帶有 `Article URL`、`Article Title`、`Category` 與 `Sub-Category` 等 Metadata 前綴的文字檔。
2. **語意分塊 (Semantic Chunking)**：
   - **技術**：`SemanticSplitterNodeParser` (門檻設為 `95%`)。
   - **作用**：計算相鄰句子的向量相似度，當主題發生顯著偏離（例如從成交費率換到金流費率）時才進行切分，保留段落政策的完整性。
3. **句子窗口標記 (Sentence Window Parsing)**：
   - **技術**：`SentenceWindowNodeParser` (預設 `window_size=3`)。
   - **作用**：檢索時只檢索精確的單句（提高檢索分數合理性），但在送給 LLM 時，會自動回填該句子前後各 3 句的上下文（確保上下文政策說明脈絡不中斷）。
4. **中介資料提取 (Metadata Extraction)**：
   - **技術**：在 `ingestion.py` 內使用正則表達式，自動提取 `url`、`title`、`category`、`sub_category`，並自動掃描內容關鍵字以打上 tags（如 `手續費/費用`、`計分/違規`、`免運/物流` 等），以便後續檢索過濾。
5. **向量化與儲存 (Storing)**：
   - **技術**：Vertex AI Embedding 或 Gemini Embedding，搭配 GCP BigQuery 欄位儲存。
   - 將 Nodes 的原始文本、Metadata 與其向量以 JSON 形式儲存於 BigQuery 資料表中，或在本地開發時存於 SQLite。

---

## 3. 在線對話管道 (Online Querying)

當賣家在 LINE 對話框輸入訊息時，即時運作的工作流。

### 核心技術與步驟：
1. **對話歷史與意圖路由 (Intent Router)**：
   - 區分「日常閒聊」與「賣家政策詢問」，若為閒聊直接回覆以省下檢索與資料庫查詢成本。
2. **問題濃縮 (Query Condensing)**：
   - 將多輪對話的歷史脈絡（如：「請問被記點會怎麼樣？」 -> 「那申訴有期限嗎？」）濃縮成一個獨立且完整的查詢句（如：「蝦皮賣家被記違規罰分的申訴期限是多久？」）。
3. **混合檢索 (Hybrid Search & RRF)**：
   - 整合向量檢索與 BM25 關鍵字檢索。關鍵字檢索對「成交手續費」、「罰分」、「OK超商」等專有名詞有極佳的精準匹配效果。使用 **RRF (Reciprocal Rerank Fusion)** 進行結果融合。
4. **相似度過濾 (Similarity Post-processing)**：
   - `SimilarityPostprocessor` (門檻設為 `0.78`)，過濾掉相關性過低的段落。
5. **防禦性 Prompt 設計 (Defensive Prompting)**：
   - 使用 XML 標籤隔離檢索外源資料，防止使用者或文章內潛在的「間接提示注入攻擊」。
6. **回答生成與輸出驗證 (Generation & Validation)**：
   - 使用 `compact` 引用友善模式合成回答，並由驗證節點檢查內容中是否包含安全注入漏洞。
7. **長期記憶與反思 (Reflection & Seller Profiles)**：
   - 根據賣家所問的主題，自動更新 BigQuery 中儲存的賣家 Profile JSON。例如當賣家詢問多次手續費問題，系統會自動在偏好中寫入關注政策，在後續對話中主動以更清晰的手續費架構回應。

---

## 4. 當前優化路線圖 (Tuning Roadmap)

針對電商賣家百科特定的業務挑戰，我們將持續優化以下三個方向：

### 優化方向 1：平台政策異動檢測 (Policy Update Tracking)
* **問題**：蝦皮手續費與罰分規則常在雙十一、年中或每季進行微調，資料庫中的文章可能會過期。
* **方案**：在爬蟲 `crawler.py` 抓取文章時，記錄網頁的更新時間（`update_time`），並與資料庫現有 Node 做比對。若官網文章有更新，則自動覆寫資料庫內舊有的節點，以保持檢索庫的絕對精準。

### 優化方向 2：手續費精準計算工具 (Calculator Tool Integration)
* **問題**：LLM 處理數學計算（如手續費率 7.5% 與金流費 2% 的加總與乘法）常會發生微小數值計算錯誤，不適合直接輸出給賣家。
* **方案**：在 LangGraph 中加入手續費計算工具 (Calculator Agent Tool)。當偵測到賣家想計算特定金額（如：「一千元的衣服實收多少？」）時，Agent 會自動提取 RAG 中的費率數字，丟給 Python 計算引擎進行運算，輸出精確無誤的對帳單明細。

### 優化方向 4：自動化分類目錄遞迴爬取 (Automated Category Traversal)
* **問題**：目前爬蟲腳本需要手動指定或在程式中寫死文章 ID（如 19182, 27708, 27709）進行抓取，無法自動感知蝦皮賣家幫助中心新增的文章與政策變更。
* **方案**：擴充爬蟲模組，使其能從蝦皮賣家幫助中心大分類的入口頁面（如 `https://seller.shopee.tw/edu/categories`）出發，自動解析各分類目錄節點，遞迴深入抓取底下所有子頁面與細部文章連結，實作全站點政策的自動化發現與同步更新。

---

## 5. Token 節省與效能優化設計 (Token Saving)

* **閒聊路由**：日常問候由 `chitchat` 節點在 30 字內直接回覆，不調用 LlamaIndex 檢索。
* **簡練模式 (Compact RAG)**：回答限制在 150 字以內，優先使用條列或表格呈現，為賣家省去大篇幅文字閱讀時間，同時省下 60% 的 LLM 生成成本。
* **反思控制**：反思優化指令控制在 150 字以內，防止 System Instructions 因多輪對話無限膨脹。
