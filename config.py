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

# Database (GCP BigQuery)
BIGQUERY_PROJECT = os.getenv("BIGQUERY_PROJECT")
if BIGQUERY_PROJECT and not os.getenv("GOOGLE_CLOUD_PROJECT"):
    os.environ["GOOGLE_CLOUD_PROJECT"] = BIGQUERY_PROJECT

# Default Model settings
MODEL_TYPE = os.getenv("MODEL_TYPE", "mock") # can be google_gemini, openai, anthropic, vertex_ai, ollama, mock

# Environment (dev or prod)
ENV = os.getenv("ENV", "dev")

class BigQueryCursorWrapper:
    def __init__(self, client, dataset_name):
        self.client = client
        self.dataset_name = dataset_name
        self._results = []
        self._row_idx = 0

    def execute(self, sql, params=None):
        from google.cloud import bigquery
        
        # BigQuery positional parameters style matches standard '?' in standard SQL, mapped using ScalarQueryParameter
        query_params = []
        if params:
            if not isinstance(params, (list, tuple)):
                params = (params,)
            
            for val in params:
                if isinstance(val, int):
                    param_type = "INT64"
                elif isinstance(val, float):
                    param_type = "FLOAT64"
                elif isinstance(val, bool):
                    param_type = "BOOL"
                else:
                    param_type = "STRING"
                query_params.append(bigquery.ScalarQueryParameter(None, param_type, val))

        job_config = bigquery.QueryJobConfig(
            default_dataset=f"{self.client.project}.{self.dataset_name}"
        )
        if query_params:
            job_config.query_parameters = query_params

        logger.info(f"Executing BigQuery: {sql} with params {params}")
        query_job = self.client.query(sql, job_config=job_config)
        result = query_job.result()
        
        self._results = []
        if result is not None:
            try:
                for row in result:
                    if row is not None:
                        try:
                            self._results.append(tuple(row))
                        except TypeError:
                            pass
            except TypeError:
                pass
        self._row_idx = 0

    def fetchone(self):
        if self._row_idx < len(self._results):
            row = self._results[self._row_idx]
            self._row_idx += 1
            return row
        return None

    def fetchall(self):
        res = self._results[self._row_idx:]
        self._row_idx = len(self._results)
        return res

class BigQueryConnectionWrapper:
    def __init__(self, project_id, dataset_name):
        from google.cloud import bigquery
        self.client = bigquery.Client(project=project_id)
        self.dataset_name = dataset_name
        self.dataset_ref = self.client.dataset(dataset_name)
        
        # Create dataset if not exists
        try:
            self.client.get_dataset(self.dataset_ref)
        except Exception:
            dataset = bigquery.Dataset(self.dataset_ref)
            dataset.location = "US"
            self.client.create_dataset(dataset, timeout=30)
            logger.info(f"Created BigQuery dataset: {dataset_name}")

    def cursor(self):
        return BigQueryCursorWrapper(self.client, self.dataset_name)

    def commit(self):
        pass

    def close(self):
        pass

def is_database_available():
    """Check if GCP BigQuery configuration is provided."""
    return BIGQUERY_PROJECT is not None and len(BIGQUERY_PROJECT.strip()) > 0

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

def initialize_bq_schema(client, dataset_name):
    """Translates schema.sql to BigQuery syntax and initializes tables."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if os.path.exists(schema_path):
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema_sql = f.read()
            
            # Simple translator from SQLite to BigQuery syntax
            statements = schema_sql.split(';')
            for stmt in statements:
                stmt = stmt.strip()
                if not stmt:
                    continue
                # Translate types & constraints
                stmt_bq = stmt
                stmt_bq = stmt_bq.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "STRING DEFAULT GENERATE_UUID()")
                stmt_bq = stmt_bq.replace("TEXT PRIMARY KEY", "STRING")
                stmt_bq = stmt_bq.replace("TEXT", "STRING")
                stmt_bq = stmt_bq.replace("DATETIME DEFAULT CURRENT_TIMESTAMP", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP()")
                stmt_bq = stmt_bq.replace("PRIMARY KEY", "") # remove other primary keys
                
                from google.cloud import bigquery
                job_config = bigquery.QueryJobConfig(
                    default_dataset=f"{client.project}.{dataset_name}"
                )
                query_job = client.query(stmt_bq, job_config=job_config)
                query_job.result()
            logger.info("Successfully initialized BigQuery schema from schema.sql translation.")
        except Exception as e:
            logger.error(f"Failed to initialize BigQuery schema: {e}")
    else:
        logger.warning(f"schema.sql not found at {schema_path}! Cannot initialize BigQuery tables.")

def get_database_connection():
    """
    Returns a database connection.
    If BIGQUERY_PROJECT is configured (and not running in pytest unit tests),
    connects to GCP BigQuery (dataset name dev/prod).
    Otherwise, connects to a local persistent SQLite file: LLM_chatbot_dev.db.
    """
    if is_testing():
        # Force local SQLite during unit tests to isolate cloud datasets
        import sqlite3
        db_file = "LLM_chatbot_test.db"
        conn = sqlite3.connect(db_file, check_same_thread=False)
        initialize_sqlite_schema(conn)
        return conn

    if is_database_available():
        db_name = "LLM_chatbot_prod" if ENV.lower() == "prod" else "LLM_chatbot_dev"
        try:
            conn = BigQueryConnectionWrapper(BIGQUERY_PROJECT, db_name)
            logger.info(f"Successfully connected to GCP BigQuery ({ENV} mode), Dataset: {db_name}")
            initialize_bq_schema(conn.client, db_name)
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to BigQuery: {e}. Falling back to local SQLite.")
    
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
            return AIMessage(content="[Mock LangChain Response] 驗證金鑰成功。蝦皮賣家百科：成交手續費率 5.5%，金流服務費 2%，出貨天數限制 2 天。")
        elif "手續費" in prompt_str or "Fees" in prompt_str or "費用" in prompt_str:
            return AIMessage(content="[Mock LangChain Response] 根據蝦皮賣家規範，單件商品成交手續費為 5.5% ~ 7.5%（視類別而定），另外金流服務費為 2%（買家刷卡或轉帳皆適用）。")
        elif "罰分" in prompt_str or "計分" in prompt_str or "違規" in prompt_str:
            return AIMessage(content="[Mock LangChain Response] 蝦皮賣家計分系統每週一更新。若發生「延遲出貨」或「未出貨率過高」，會被記 1-2 分，累積滿 3 分會限制參加主題活動，滿 6 分則限制編輯商品。")
        elif "優化系統指令" in prompt_str or "update_instructions" in prompt_str:
            return AIMessage(content="系統指令已優化：請特別專注於蝦皮手續費計算規章與賣家違規罰分處置說明。")
        else:
            return AIMessage(content=f"[Mock LangChain Response] 收到您的訊息。當前的模型配置為 {self.model_type}。我是蝦皮賣家百科助手，請問有什麼我可以協助您的？")

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
            text = "[Mock LlamaIndex Response] Found secure token VERIFY_SECURE_TOKEN_99. Shopee Seller: standard commission is 5.5%, payment service fee is 2%, shipment processing deadline is 2 days."
        elif "手續費" in prompt or "費用" in prompt:
            text = "[Mock LlamaIndex Response] 蝦皮賣家成交手續費主要依商品售價乘以手續費率（常態為 5.5% - 7.5%），若有加入免運專案或蝦幣回饋專案會另計合約費率。"
        elif "罰分" in prompt or "計分" in prompt:
            text = "[Mock LlamaIndex Response] 蝦皮賣家若單週「延遲出貨率」大於等於 10% 會被記 1 分，大於等於 15% 且延遲訂單大於等於 50 筆會被記 2 分。"
        else:
            text = "[Mock LlamaIndex Response] 本地 LlamaIndex 測試成功，已檢索蝦皮賣家百科相關文章內容。"
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
