系統架構與程式實作文件：基於 LangChain 與 LlamaIndex 的財報檢索與對話系統

本文件為資深技術引導與架構師專用，詳述如何整合 LangChain 的工作流編排能力與 LlamaIndex 的數據處理深度，構建一套針對複雜財報數據的生產級檢索增強生成（RAG）系統。


--------------------------------------------------------------------------------


1. 系統概述與 RAG 核心架構價值

為解決大型語言模型（LLM）在處理企業財務數據時的侷限，我們必須實施一套多階段的 RAG 管道。這不僅是技術堆疊的組合，更是為了解決以下關鍵瓶頸：

* 有限的上下文窗口 (Finite Context Window)：LLM 無法原生處理數百頁的 SEC 申報文件或年度合併報表，需要精確的片段切分。
* 靜態知識的非決定性 (Non-deterministic Static Knowledge)：LLM 的訓練集在特定時間點截止，無法掌握最新的市場動態與季度結算數據。

RAG 實作的核心支柱：

1. 索引階段 (Indexing)：將非結構化財務文本轉化為結構化、可檢索的向量與元數據索引（離線預處理）。
2. 檢索與生成 (Retrieval & Generation)：在運行時動態召回相關背景，並將其注入提示詞（Prompt），使模型生成的答案具備事實根據（Grounding）。


--------------------------------------------------------------------------------


2. 技術框架策略對比：LangChain vs. LlamaIndex

在系統設計上，我們選擇「雙框架併行」策略，而非單一選擇，其戰略考量如下表：

特性	LangChain	LlamaIndex
系統定位	Workflow Engine (工作流引擎)	RAG 專門化產品包
技術優勢	具備強大的生態系統與 LCEL (LangChain Expression Language)，適合建構複雜的 Agentic Flow 與狀態管理。	專精於數據分層、索引結構優化與多樣化的檢索器模式。
實作開銷 (Overhead)	較高，組件原子化程度高，開發者需自行拼裝細節邏輯。	較低，針對常見 RAG 場景（如 CondensePlusContext）提供了高度封裝。
戰略用途	負責 Agent 的狀態維護 (LangGraph)、多輪對話邏輯與跨工具調度。	負責 高性能數據解析 (Parsing)、索引構建與檢索算法調優。


--------------------------------------------------------------------------------


3. 模型選型與高效通訊機制

系統採用多階段模型組合，以最大化推理效能並控制運算成本：

1. Chat Model (如 Google Gemini)：作為中央決策與反思核心，負責最終答案生成。
2. Embedding Model (如 VertexAI)：將文本轉化為數值向量。
3. Reranker (如 CohereRerank)：在初篩後進行交叉編碼（Cross-Encoding）精排，顯著提升長尾問題的準確度。

關鍵實作细节： 使用 LangChain 的 initChatModel 時，需配置 responseFormat="content_and_artifact"。此機制允許系統分離模型生成的字串與底層檢索到的原始文件元數據，確保前端 UI 能在不干擾對話流的情況下，展示精確的引用來源。


--------------------------------------------------------------------------------


4. 數據索引與檢索優化實作 (LlamaIndex)

財務數據包含大量專業縮寫（如 Ticker Symbols: AAPL）與精確數值，傳統向量檢索常發生語義漂移。我們採用的「混合檢索」與「父文件檢索」方案如下：

* 優化技術策略：
  * 語義分塊 (Semantic Splitting)：解決固定長度切分導致的上下文斷裂。
  * 句子窗口 (Sentence Window)：檢索時回填上下文，解決「分割坑洞 (Splitter Pitfall)」。
  * 父文件檢索 (Parent-Document Retrieval)：檢索精細的小塊（高召回），但回傳給模型較大的父節點內容（高精準）。
  * BM25 關鍵字檢索：針對股票代碼、會計科目（如 EBITDA）提供精確匹配。

Pseudo Code：高級索引構建與驗證

from llama_index.core.node_parser import SemanticSplitterNodeParser, SentenceWindowNodeParser
from llama_index.core.indices.keyword_table import SimpleKeywordTableIndex
from llama_index.core.postprocessor import SimilarityPostprocessor

# 1. 初始化解析器：語義邊界 + 上下文窗口
semantic_parser = SemanticSplitterNodeParser(buffer_size=1, breakpoint_percentile_threshold=95)
window_parser = SentenceWindowNodeParser(window_size=2, window_metadata_key="window")

# 2. 處理文檔並建立雙索引
semantic_nodes = semantic_parser.get_nodes_from_documents(docs)
final_nodes = window_parser.get_nodes_from_documents(semantic_nodes)

vector_index = VectorStoreIndex(final_nodes)
keyword_index = SimpleKeywordTableIndex(final_nodes) # 修正：定義關鍵字索引

# 3. 混合檢索器與相似度過濾
retriever = QueryFusionRetriever(
    retrievers=[
        vector_index.as_retriever(similarity_top_k=5),
        keyword_index.as_retriever(similarity_top_k=5)
    ],
    mode="reciprocal_rerank" # RRF 融合
)

# 設定相似度門檻，確保財報數據的嚴謹性
postprocessor = SimilarityPostprocessor(similarity_cutoff=0.78)



--------------------------------------------------------------------------------


5. GCP BigQuery 環境與對話持久化

在生產環境中，我們利用 GCP 的 BigQuery 實現對話歷史、使用者偏好以及分塊數據的統一存儲。

* 持久化記憶：採用 BigQuery 客製化連線包裝實作，並使用 DELETE + INSERT 保證 SQL 相容性，確保存儲在資料集而非記憶體，支持跨會話的 Context 恢復與偏好更新。

Pseudo Code：BigQuery 整合

from google.cloud import bigquery

# 初始化 BigQuery 客戶端與作業設定
client = bigquery.Client(project="your_project_id")
job_config = bigquery.QueryJobConfig(default_dataset="your_project_id.LLM_chatbot_dev")

# 寫入對話歷史
sql = "INSERT INTO chat_history (session_id, message_type, content) VALUES (?, ?, ?)"
client.query(sql, job_config=job_config)



--------------------------------------------------------------------------------


6. Agentic RAG 與 Meta-Prompting 反思機制

利用 LangGraph 實作具備「自我進化」能力的 Agent。我們區分兩種長效記憶：語義記憶 (Semantic Memory) 儲存財報事實，程序記憶 (Procedural Memory) 儲存優化後的系統指令。

* 反思節點 (Reflection Node)：透過 update_instructions 邏輯，根據用戶回饋與檢索失敗記錄，動態更新 Agent 的 System Prompt。

Pseudo Code：LangGraph 與指令儲存

def update_instructions_node(state: AgentState, config: RunnableConfig):
    # 獲取當前記憶存儲中的 Prompt
    store = config["configurable"].get("store")
    current_prompt = store.get(("prompts", "rag_agent"), "default_key")
    
    # 根據 state["messages"] 中的用戶回饋進行 Meta-prompting 反思
    new_instructions = llm.invoke(f"根據以下對話優化系統指令: {current_prompt} ...")
    
    # 更新程序記憶 (Procedural Memory)
    store.put(("prompts", "rag_agent"), "default_key", {"content": new_instructions})
    return {"messages": [AIMessage(content="系統指令已優化。")]}

# 流程定義：Query Enhancement -> Retrieve -> Validate -> (Optional) Update Instructions
workflow = StateGraph(AgentState)
workflow.add_node("update_instructions", update_instructions_node)
workflow.add_edge("answer_validation", "update_instructions")



--------------------------------------------------------------------------------


7. 系統安全性與「審計友善」的回應合成

針對財務數據的敏感度，安全性是架構設計的首要任務：

* 關鍵安全對策：
  * 防範間接提示注入 (Indirect Prompt Injection)：將此視為 Critical 級別漏洞。實作上需使用防禦性提示词，並利用 XML 標籤（如 <context>）嚴格分隔檢索到的外部數據與模型指令。
* 回應合成模式 (Response Mode)：
  * Compact 模式：本系統強制要求使用 compact 模式。與 tree_summarize 相比，它更具 「引用友善 (Citation-friendly)」 特質，內容簡練且嚴格依賴檢索節點，能大幅降低財務分析中的幻覺風險，滿足審計合規需求。


--------------------------------------------------------------------------------


8. 持續評估與 LangSmith 監控

為量化 RAG 效能，我們定義了兩個核心量化指標：

1. 忠實度 (Faithfulness)：驗證生成答案是否完全源於檢索片段（無幻覺）。
2. 正確率 (Correctness)：對比生成的回答與黃金標準答案（Ground Truth）。

監控機制： 系統深度整合 LangSmith，實現全鏈路 Trace 追蹤。這使架構師能即時監控 Embedding 延遲、LLM 標記消耗以及各個節點（如 Reranker）的效能瓶頸，確保在高頻交易分析場景下的系統穩定性。
