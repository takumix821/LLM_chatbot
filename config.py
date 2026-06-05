import os
import logging
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("LLMChatbotConfig")

# Load environment variables from .env file if present
load_dotenv()

# Cloud and API Credentials
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
VERTEX_API_KEY = os.getenv("VERTEX_API_KEY") # or GCP Credentials

# Line Bot Credentials
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "mock_line_channel_access_token")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "mock_line_channel_secret")

# Database (AlloyDB / Postgres)
DATABASE_URL = os.getenv("DATABASE_URL") # format: postgresql+psycopg2://user:password@host:port/dbname

# Default Model settings
MODEL_TYPE = os.getenv("MODEL_TYPE", "mock") # can be google_gemini, openai, anthropic, vertex_ai, ollama, mock

# Environment Environment (dev or prod)
ENV = os.getenv("ENV", "dev")

def get_cloud_database_url():
    """
    Returns the cloud database connection URL rewritten with dev/prod suffix.
    Example: postgresql+psycopg2://user:pass@host:port/LLM_chatbot_dev
    """
    if not DATABASE_URL:
        return None
    # Strip any trailing slashes
    clean_url = DATABASE_URL.strip().rstrip('/')
    # Split by the last slash to replace or append the database name
    base_url = clean_url.rsplit('/', 1)[0]
    db_name = "LLM_chatbot_prod" if ENV.lower() == "prod" else "LLM_chatbot_dev"
    return f"{base_url}/{db_name}"

def is_database_available():
    """Check if database connection string is provided."""
    return DATABASE_URL is not None and len(DATABASE_URL.strip()) > 0

def initialize_sqlite_schema(conn):
    """Reads schema.sql and runs it on the connection to set up tables."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if os.path.exists(schema_path):
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema_sql = f.read()
            cursor = conn.cursor()
            cursor.executescript(schema_sql)
            conn.commit()
            logger.info("Successfully initialized SQLite schema from schema.sql.")
        except Exception as e:
            logger.error(f"Failed to initialize SQLite schema: {e}")
    else:
        logger.warning(f"schema.sql not found at {schema_path}! Cannot initialize database tables.")

def get_database_connection():
    """
    Returns a database connection.
    If DATABASE_URL is configured, connects to Cloud AlloyDB/PostgreSQL (dev or prod name).
    Otherwise, connects to a local persistent SQLite file: LLM_chatbot_dev.db.
    """
    if is_database_available():
        cloud_url = get_cloud_database_url()
        try:
            import psycopg2
            conn = psycopg2.connect(cloud_url)
            logger.info(f"Successfully connected to Cloud Database ({ENV} mode): {cloud_url.rsplit('/', 1)[-1]}")
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to cloud database: {e}. Falling back to local SQLite.")
    
    # Fallback to local persistent SQLite file
    import sqlite3
    db_file = "LLM_chatbot_dev.db"
    logger.info(f"Using local persistent SQLite database file: {db_file}")
    conn = sqlite3.connect(db_file, check_same_thread=False)
    # Initialize schema tables
    initialize_sqlite_schema(conn)
    return conn

# Mock Chat Model class for LangChain local testing
class MockLangChainLLM:
    """Mock LLM class for LangChain local testing without active API Keys."""
    def __init__(self, model_type="mock"):
        self.model_type = model_type
        
    def invoke(self, prompt, **kwargs):
        from langchain_core.messages import AIMessage
        prompt_str = str(prompt)
        
        # Simple mock reasoning/response logic
        if "VERIFY_SECURE_TOKEN_99" in prompt_str:
            return AIMessage(content="[Mock LangChain Response] Verification token detected in context. Financial results: Net revenue was $119,575 million with gross margin 45.9%. Operating income was $40,373 million.")
        elif "2024Q1" in prompt_str or "Revenue" in prompt_str or "營收" in prompt_str:
            return AIMessage(content="[Mock LangChain Response] 根據 2024Q1 財報數據，Apple Inc. 營收為 1,195.75 億美元（年增 2%），毛利率為 45.9%，淨利潤為 339.16 億美元。")
        elif "優化系統指令" in prompt_str or "update_instructions" in prompt_str:
            return AIMessage(content="系統指令已優化：請特別專注於 Ticker AAPL 及其毛利率 Gross Margin 與資本支出 Capex 的比對。")
        else:
            return AIMessage(content=f"[Mock LangChain Response] 收到您的訊息。當前的模型配置為 {self.model_type}。請問有什麼我可以協助您的？")

# Mock LLM and Embeddings for LlamaIndex local testing
from llama_index.core.llms import CustomLLM, CompletionResponse, CompletionResponseGen, LLMMetadata
from llama_index.core.embeddings import BaseEmbedding
from typing import Any

class MockLlamaIndexLLM(CustomLLM):
    """Mock Custom LLM for LlamaIndex."""
    context_window: int = 4096
    num_output: int = 1000
    model_name: str = "mock-llamaindex-llm"
    
    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=self.context_window,
            num_output=self.num_output,
            model_name=self.model_name
        )
        
    def complete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
        if "VERIFY_SECURE_TOKEN_99" in prompt:
            text = "[Mock LlamaIndex Response] Found secure token VERIFY_SECURE_TOKEN_99 in context. Apple FY2024Q1 revenue: $119,575 million. Gross Margin: 45.9%."
        elif "2024Q1" in prompt or "營收" in prompt:
            text = "[Mock LlamaIndex Response] 2024Q1 蘋果公司營收達到 1,195.75 億美元（成長 2%），毛利率為 45.9%，主要由 iPhone 與服務收入帶動。"
        else:
            text = "[Mock LlamaIndex Response] 本地 LlamaIndex 測試成功，已檢索相關文檔內容。"
        return CompletionResponse(text=text)
        
    def stream_complete(self, prompt: str, **kwargs: Any) -> CompletionResponseGen:
        raise NotImplementedError("Streaming not implemented in mock LLM")

class MockLlamaIndexEmbedding(BaseEmbedding):
    """Mock Embedding class that creates dummy vectors."""
    embed_dim: int = 8
    
    def __init__(self, embed_dim: int = 8, **kwargs: Any):
        super().__init__(embed_dim=embed_dim, **kwargs)
        
    def _generate_vector(self, text: str) -> list[float]:
        # Generate a deterministic vector with unique components based on text hash
        import hashlib
        h = hashlib.md5(text.encode('utf-8')).digest()
        # Create a list of floats normalized between -1.0 and 1.0
        vector = []
        for i in range(self.embed_dim):
            # Use chunks of the hash to create pseudo-random values
            byte_idx = (i * 2) % len(h)
            val = (h[byte_idx] + h[(byte_idx + 1) % len(h)] * 256) / 65535.0
            vector.append(val)
        return vector
        
    def _get_query_embedding(self, query: str) -> list[float]:
        return self._generate_vector(query)
        
    def _get_text_embedding(self, text: str) -> list[float]:
        return self._generate_vector(text)
        
    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

def is_testing() -> bool:
    """Helper to detect if code is running in a pytest test environment."""
    import sys
    return "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ

def get_langchain_llm(model_type: str = None):
    """
    Initializes a LangChain Chat Model based on specified model_type.
    Falls back to MockLangChainLLM if API keys are missing or when testing.
    """
    if is_testing():
        logger.info("Test environment detected. Forcing Mock LangChain LLM.")
        return MockLangChainLLM("mock")
        
    provider = model_type or MODEL_TYPE
    logger.info(f"Initializing LangChain LLM for provider: {provider}")
    
    if provider == "google_gemini" and GEMINI_API_KEY:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            # Configured with responseFormat="content_and_artifact" as requested in doc.md
            return ChatGoogleGenerativeAI(
                model="gemini-1.5-flash",
                google_api_key=GEMINI_API_KEY,
                temperature=0,
                response_format={"type": "json_object"}  # Simulating content_and_artifact response configurations
            )
        except Exception as e:
            logger.warning(f"Failed to load ChatGoogleGenerativeAI: {e}. Falling back to mock.")
            
    elif provider == "openai" and OPENAI_API_KEY:
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model="gpt-4o-mini", api_key=OPENAI_API_KEY, temperature=0)
        except Exception as e:
            logger.warning(f"Failed to load ChatOpenAI: {e}. Falling back to mock.")
            
    elif provider == "anthropic" and ANTHROPIC_API_KEY:
        try:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(model=ANTHROPIC_MODEL, api_key=ANTHROPIC_API_KEY, temperature=0)
        except Exception as e:
            logger.warning(f"Failed to load ChatAnthropic: {e}. Falling back to mock.")
            
    elif provider == "ollama":
        try:
            from langchain_community.chat_models import ChatOllama
            return ChatOllama(model="llama3", temperature=0)
        except Exception as e:
            logger.warning(f"Failed to load ChatOllama: {e}. Falling back to mock.")
            
    # Default fallback to mock
    logger.info("Using Mock LangChain LLM for local run.")
    return MockLangChainLLM(provider)

def get_llamaindex_llm(model_type: str = None):
    """
    Initializes a LlamaIndex LLM based on specified model_type.
    Falls back to MockLlamaIndexLLM if API keys are missing or when testing.
    """
    if is_testing():
        logger.info("Test environment detected. Forcing Mock LlamaIndex LLM.")
        return MockLlamaIndexLLM()
        
    provider = model_type or MODEL_TYPE
    logger.info(f"Initializing LlamaIndex LLM for provider: {provider}")
    
    if provider == "google_gemini" and GEMINI_API_KEY:
        try:
            from llama_index.llms.gemini import Gemini
            return Gemini(model="models/gemini-1.5-flash", api_key=GEMINI_API_KEY, temperature=0)
        except Exception as e:
            logger.warning(f"Failed to load Gemini LlamaIndex: {e}. Falling back to mock.")
            
    elif provider == "openai" and OPENAI_API_KEY:
        try:
            from llama_index.llms.openai import OpenAI
            return OpenAI(model="gpt-4o-mini", api_key=OPENAI_API_KEY, temperature=0)
        except Exception as e:
            logger.warning(f"Failed to load OpenAI LlamaIndex: {e}. Falling back to mock.")
            
    elif provider == "anthropic" and ANTHROPIC_API_KEY:
        try:
            from llama_index.llms.anthropic import Anthropic
            return Anthropic(model=ANTHROPIC_MODEL, api_key=ANTHROPIC_API_KEY, temperature=0)
        except Exception as e:
            logger.warning(f"Failed to load Anthropic LlamaIndex: {e}. Falling back to mock.")
            
    # Fallback to custom mock
    logger.info("Using Mock LlamaIndex LLM for local run.")
    return MockLlamaIndexLLM()

def get_llamaindex_embedding(model_type: str = None):
    """
    Initializes a LlamaIndex Embedding model.
    Falls back to MockLlamaIndexEmbedding when testing or if keys are missing.
    """
    if is_testing():
        logger.info("Test environment detected. Forcing Mock LlamaIndex Embedding.")
        return MockLlamaIndexEmbedding()
        
    provider = model_type or MODEL_TYPE
    logger.info(f"Initializing LlamaIndex Embedding for provider: {provider}")
    
    if provider == "openai" and OPENAI_API_KEY:
        try:
            from llama_index.embeddings.openai import OpenAIEmbedding
            return OpenAIEmbedding(api_key=OPENAI_API_KEY)
        except Exception as e:
            logger.warning(f"Failed to load OpenAIEmbedding: {e}. Falling back to mock.")
            
    elif provider == "google_gemini" and GEMINI_API_KEY:
        try:
            from llama_index.embeddings.gemini import GeminiEmbedding
            return GeminiEmbedding(api_key=GEMINI_API_KEY)
        except Exception as e:
            logger.warning(f"Failed to load GeminiEmbedding: {e}. Falling back to mock.")
            
    # Fallback to mock embedding
    logger.info("Using Mock LlamaIndex Embedding for local run.")
    return MockLlamaIndexEmbedding()

def get_line_webhook_config():
    """
    Returns Line Connection Credentials.
    """
    return {
        "channel_access_token": LINE_CHANNEL_ACCESS_TOKEN,
        "channel_secret": LINE_CHANNEL_SECRET
    }
