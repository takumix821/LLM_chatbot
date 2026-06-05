import os
import sys
import logging
from colorama import init, Fore, Style

import config
from ingestion import IngestionPipeline, get_hybrid_search_results
from agent import FinancialAgent, get_chat_history_helper, get_user_profile, save_user_profile
from langchain_core.messages import HumanMessage

# Initialize colorama for clean terminal outputs
init(autoreset=True)

# Minimize logging logs to make terminal display clean
logging.getLogger("LLMChatbotConfig").setLevel(logging.WARNING)
logging.getLogger("LLMChatbotIngestion").setLevel(logging.WARNING)
logging.getLogger("LLMChatbotAgent").setLevel(logging.WARNING)

def print_header(title):
    print(f"\n{Fore.CYAN}{Style.BRIGHT}{'='*60}")
    print(f"{Fore.CYAN}{Style.BRIGHT} {title}")
    print(f"{Fore.CYAN}{Style.BRIGHT}{'='*60}\n")

def run_local_demo():
    print_header("GCP 智能財報分析助手 - 本地測試與展示主程式")
    
    # 1. Check directory and create mock data if not existing
    data_dir = "mock_data"
    print(f"{Fore.YELLOW}[Step 1] 初始化 LlamaIndex 數據管道...")
    
    pipeline = IngestionPipeline(data_dir=data_dir)
    vector_index, keyword_index, fusion_retriever = pipeline.run_pipeline()
    
    if fusion_retriever is None:
        print(f"{Fore.RED}Error: 無法初始化數據管道。請確認 {data_dir}/ 中有放置財報文件。")
        sys.exit(1)
        
    print(f"{Fore.GREEN}LlamaIndex 數據分塊與混合索引建立成功！")
    
    # 2. Setup SQLite Connection for Memory
    print(f"\n{Fore.YELLOW}[Step 2] 初始化本地數據庫記憶體與用戶偏好 Profile...")
    conn = config.get_database_connection()
    session_id = "test_user_session_001"
    
    history = get_chat_history_helper(session_id, conn)
    profile = get_user_profile(session_id, conn)
    
    print(f"{Fore.GREEN}連線配置加載完成！當前使用的是 {Fore.MAGENTA}{config.MODEL_TYPE} {Fore.GREEN}模式。")
    print(f"預設用戶偏好 Profile:\n{Fore.WHITE}{profile}")
    
    # 3. Setup LangChain Agent
    print(f"\n{Fore.YELLOW}[Step 3] 建立 LangGraph 對話代理...")
    agent = FinancialAgent(retriever=fusion_retriever)
    graph = agent.build_graph()
    print(f"{Fore.GREEN}LangGraph 工作流編譯成功！")
    
    # 4. Prompt options
    print_header("準備就緒 - 請選擇測試模式")
    print("1. 測試 LlamaIndex 獨立檢索功能 (語意分塊 + 句子窗口 + 混合 RRF)")
    print("2. 測試 LangChain RAG 代理對話 (包含問題濃縮、防禦性 Prompt、反思機制)")
    print("3. 進行完整交互式問答 (按 'q' 退出)")
    
    choice = input("\n請輸入 1, 2 或 3: ").strip()
    
    if choice == "1":
        print_header("LlamaIndex 獨立混合檢索測試")
        test_queries = [
            "2026Q1 營收與毛利率是多少？",
            "雲端運算業務的營收佔比與表現如何？",
            "有沒有關於半導體代工服務與 wafer allocation 的描述？"
        ]
        
        for q in test_queries:
            print(f"\n{Fore.YELLOW}查詢語句: {q}")
            results = get_hybrid_search_results(q, fusion_retriever, similarity_cutoff=0.78)
            print(f"{Fore.GREEN}檢索到符合篩選門檻 (>=0.78) 的節點數量: {len(results)}")
            
            for idx, node in enumerate(results):
                node_id = getattr(node.node, "node_id", "N/A")
                start_idx = node.node.metadata.get("start_char_idx", "N/A")
                end_idx = node.node.metadata.get("end_char_idx", "N/A")
                print(f"\n  {Fore.CYAN}--- 節點 {idx+1} ---")
                print(f"  {Fore.CYAN}  * 節點 ID: {node_id}")
                print(f"  {Fore.CYAN}  * 字符區間: {start_idx} ~ {end_idx} (長度: {len(node.node.text)} 字)")
                print(f"  {Fore.CYAN}  * 檢索分數: {node.score:.4f}")
                print(f"  {Fore.CYAN}  * 來源文件: {node.node.metadata.get('file_name', 'N/A')}")
                print(f"  {Fore.WHITE}  * 節點內容:\n    {node.node.text}")
                # Print window context if exists
                window = node.node.metadata.get("window")
                if window:
                    print(f"  {Fore.BLUE}  * 句子窗口上下文 (Window):\n    {window.strip()}")
                    
    elif choice == "2":
        print_header("LangChain RAG 代理對話測試")
        
        test_conversation = [
            "哈囉，今天天氣真好！", # General chitchat -> route to chitchat node
            "我想查一下 2026Q1 的營收表現？", # Financial RAG -> route to RAG
            "那麼，那季的毛利率與 Services 營收各是多少？" # Follow-up -> query enhancement -> RAG
        ]
        
        state = {
            "messages": [],
            "standalone_query": "",
            "context_nodes": [],
            "instructions": "你是一個專業的智能財報分析助手。",
            "user_profile": profile,
            "validation_status": "",
            "session_id": session_id
        }
        
        for user_msg in test_conversation:
            print(f"\n{Fore.YELLOW}User: {user_msg}")
            
            # Record user message to history & state
            history.add_user_message(user_msg)
            state["messages"].append(HumanMessage(content=user_msg))
            
            # Run Graph
            output_state = graph.invoke(state)
            
            # Retrieve last AI message
            ai_msg = output_state["messages"][-1].content
            history.add_ai_message(ai_msg)
            
            # Update state with latest graph outputs
            state = output_state
            
            print(f"{Fore.GREEN}Assistant: {ai_msg}")
            if state.get("standalone_query"):
                print(f"{Fore.MAGENTA}  [濃縮查詢句]: {state['standalone_query']}")
            print(f"{Fore.BLUE}  [驗證狀態]: {state.get('validation_status')}")
            print(f"{Fore.CYAN}  [當前指令]: {state.get('instructions')}")
            
    elif choice == "3":
        print_header("開始交互式問答 (輸入 'q' 離開)")
        
        state = {
            "messages": [],
            "standalone_query": "",
            "context_nodes": [],
            "instructions": "你是一個專業的智能財報分析助手。",
            "user_profile": profile,
            "validation_status": "",
            "session_id": session_id
        }
        
        while True:
            try:
                user_msg = input(f"\n{Fore.YELLOW}你: ").strip()
                if not user_msg:
                    continue
                if user_msg.lower() == 'q':
                    print(f"\n{Fore.GREEN}謝謝使用，再見！")
                    break
                    
                history.add_user_message(user_msg)
                state["messages"].append(HumanMessage(content=user_msg))
                
                # Run graph
                output_state = graph.invoke(state)
                
                # Get response
                ai_msg = output_state["messages"][-1].content
                history.add_ai_message(ai_msg)
                
                state = output_state
                
                print(f"{Fore.GREEN}助手: {ai_msg}")
                if state.get("standalone_query"):
                    print(f"{Fore.MAGENTA}  [濃縮查詢句]: {state['standalone_query']}")
                print(f"{Fore.BLUE}  [當前偏好]: {state['user_profile']['extracted_knowledge']}")
                
            except KeyboardInterrupt:
                print(f"\n{Fore.GREEN}離開對話。")
                break
    else:
        print(f"{Fore.RED}無效選擇。離開程式。")

if __name__ == "__main__":
    run_local_demo()
