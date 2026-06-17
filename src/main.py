import os
import logging
import json
from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

import config
from ingestion import IngestionPipeline
from agent import FinancialAgent, get_chat_history_helper, get_user_profile, save_user_profile
from langchain_core.messages import HumanMessage

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("LLMChatbotServer")

# Minimize internal configs logging to keep terminal output clean
logging.getLogger("LLMChatbotConfig").setLevel(logging.WARNING)
logging.getLogger("LLMChatbotIngestion").setLevel(logging.WARNING)
logging.getLogger("LLMChatbotAgent").setLevel(logging.WARNING)

app = FastAPI(title="GCP Shopee Seller Encyclopedia Chatbot LINE Webhook Server")

# Retrieve LINE credentials from config
line_config = config.get_line_webhook_config()
line_bot_api = LineBotApi(line_config["channel_access_token"])
handler = WebhookHandler(line_config["channel_secret"])

# Initialize Ingestion Pipeline & Agent globally
logger.info("[Server Init] Initializing Ingestion Pipeline and Retrievers...")
pipeline = IngestionPipeline(data_dir="mock_data")
vector_index, keyword_index, fusion_retriever = pipeline.run_pipeline()
if fusion_retriever is None:
    logger.warning("[Server Init] Failed to initialize RAG pipeline. Ensure mock_data directory has crawled seller articles (running crawler first may be required).")
else:
    logger.info("[Server Init] RAG Pipeline initialized successfully.")

agent = FinancialAgent(retriever=fusion_retriever)
graph = agent.build_graph()
logger.info("[Server Init] LangGraph agent workflow compiled successfully.")

@app.get("/")
def health_check():
    return {
        "status": "ok",
        "model_type": config.MODEL_TYPE,
        "database": "BigQuery" if config.is_database_available() else "SQLite",
        "dataset_mode": config.ENV
    }

@app.post("/webhook")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature")
    if not signature:
        logger.error("Missing X-Line-Signature header")
        raise HTTPException(status_code=400, detail="Missing X-Line-Signature header")
        
    body = await request.body()
    body_str = body.decode("utf-8")
    
    try:
        handler.handle(body_str, signature)
    except InvalidSignatureError:
        logger.error("Invalid signature detected")
        raise HTTPException(status_code=400, detail="Invalid signature")
        
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text
    user_id = event.source.user_id
    reply_token = event.reply_token
    
    logger.info(f"[LINE Event] Received message from {user_id}: {user_msg}")
    
    # Establish DB connection for this request
    conn = config.get_database_connection()
    try:
        # Load user history and preference profile (isolated by LINE user_id)
        history = get_chat_history_helper(user_id, conn)
        profile = get_user_profile(user_id, conn)
        
        # Build initial graph state
        state = {
            "messages": [],
            "standalone_query": "",
            "context_nodes": [],
            "instructions": "你是一個專業的蝦皮賣家百科智能助手。請簡短精煉、精準地回答賣家的問題。",
            "user_profile": profile,
            "validation_status": "",
            "session_id": user_id
        }
        
        # Populate history state (limit to last 10 messages to manage context window)
        db_messages = history.messages[-10:] if hasattr(history, "messages") else []
        for msg in db_messages:
            state["messages"].append(msg)
            
        # Append current user message
        state["messages"].append(HumanMessage(content=user_msg))
        history.add_user_message(user_msg)
        
        # Invoke LangGraph workflow
        output_state = graph.invoke(state)
        
        # Extract reply content
        ai_msg = output_state["messages"][-1].content
        history.add_ai_message(ai_msg)
        
        # Save updated user profile back to database
        if "user_profile" in output_state:
            save_user_profile(user_id, output_state["user_profile"], conn)
            
        # Reply to LINE
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=ai_msg)
        )
        logger.info(f"[LINE Event] Successfully replied to {user_id}")
    except Exception as e:
        logger.error(f"[LINE Event] Error handling event: {e}", exc_info=True)
        try:
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text="抱歉，系統在處理您的訊息時遇到了技術問題，請稍後再試。")
            )
        except Exception as reply_err:
            logger.error(f"[LINE Event] Failed to send error fallback reply: {reply_err}")
    finally:
        conn.close()
