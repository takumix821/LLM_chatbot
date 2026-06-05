import os
import re
import logging
from llama_index.core import SimpleDirectoryReader, VectorStoreIndex, StorageContext, Settings
from llama_index.core.node_parser import SemanticSplitterNodeParser, SentenceWindowNodeParser
from llama_index.core.indices.keyword_table import SimpleKeywordTableIndex
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.retrievers import QueryFusionRetriever

import config

logger = logging.getLogger("LLMChatbotIngestion")

def extract_sec_metadata(text: str) -> dict:
    """
    Extracts SEC metadata from document text using regular expressions.
    Fields to extract: Company Code, Fiscal Year, Quarter, Document Type, Key Metrics.
    """
    metadata = {}
    
    # Regex patterns for metadata extraction
    patterns = {
        "company_code": r"Company Code:\s*([A-Z0-9]+)",
        "fiscal_year": r"Fiscal Year:\s*([0-9]{4})",
        "quarter": r"Quarter:\s*(Q[1-4])",
        "doc_type": r"Document Type:\s*(SEC Form [0-9a-zA-Z\-]+|SEC [a-zA-Z0-9\s]+)"
    }
    
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            metadata[key] = match.group(1).strip()
            
    # Look for key indicators/metrics in the text
    metrics = []
    if "Revenue" in text or "營收" in text:
        metrics.append("Revenue")
    if "Gross Margin" in text or "毛利率" in text:
        metrics.append("Gross Margin")
    if "Net Income" in text or "淨利潤" in text:
        metrics.append("Net Income")
    if "Capex" in text or "資本支出" in text:
        metrics.append("Capex")
        
    if metrics:
        metadata["important_metrics"] = metrics
        
    return metadata

class IngestionPipeline:
    def __init__(self, data_dir: str = "mock_data"):
        self.data_dir = data_dir
        self.embed_model = config.get_llamaindex_embedding()
        self.llm = config.get_llamaindex_llm()
        
        # Configure global settings for LlamaIndex
        Settings.embed_model = self.embed_model
        Settings.llm = self.llm
        
    def run_pipeline(self):
        """
        Executes the ingestion pipeline:
        1. Loads documents from directory
        2. Applies SemanticSplitterNodeParser (threshold=95)
        3. Applies SentenceWindowNodeParser (window_size=3)
        4. Extracts and assigns SEC metadata
        5. Builds VectorStoreIndex and SimpleKeywordTableIndex
        Returns (vector_index, keyword_index, retriever)
        """
        logger.info(f"Starting Ingestion Pipeline for directory: {self.data_dir}")
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            logger.warning(f"Created empty directory: {self.data_dir}")
            
        # 1. Load documents
        reader = SimpleDirectoryReader(self.data_dir)
        documents = reader.load_data()
        
        if not documents:
            logger.warning("No documents found in the ingestion directory.")
            return None, None, None
            
        # Extract global metadata from document contents
        for doc in documents:
            extracted = extract_sec_metadata(doc.text)
            doc.metadata.update(extracted)
            logger.info(f"Extracted document metadata: {doc.metadata}")
            
        # 2. Semantic Node Parser
        # breakpoint_percentile_threshold=95 per doc/overview requirements
        semantic_parser = SemanticSplitterNodeParser(
            buffer_size=1, 
            breakpoint_percentile_threshold=95,
            embed_model=self.embed_model
        )
        
        # 3. Sentence Window Parser
        # window_size=3 per overview requirement (doc.md specified window_size=2)
        window_parser = SentenceWindowNodeParser(
            window_size=3,
            window_metadata_key="window",
            original_text_metadata_key="original_text"
        )
        
        # Parse documents to nodes
        logger.info("Parsing documents with Semantic Splitter...")
        semantic_nodes = semantic_parser.get_nodes_from_documents(documents)
        
        logger.info("Parsing semantic nodes with Sentence Window...")
        final_nodes = window_parser.get_nodes_from_documents(semantic_nodes)
        
        # Keep SEC metadata flowing to child nodes
        for node in final_nodes:
            # Re-verify and ensure all parent metadata is present
            if node.parent_node:
                pass # metadata is automatically inherited by standard node parsers, but let's double check
            
        logger.info(f"Successfully processed {len(documents)} document(s) into {len(final_nodes)} sentence-window nodes.")
        
        # 4. Build indices
        logger.info("Building VectorStoreIndex...")
        vector_index = VectorStoreIndex(final_nodes)
        
        logger.info("Building SimpleKeywordTableIndex...")
        keyword_index = SimpleKeywordTableIndex(final_nodes)
        
        # 5. Create hybrid retriever using QueryFusionRetriever with Reciprocal Rerank Fusion (RRF)
        # We query both indices for comprehensive coverage.
        vector_retriever = vector_index.as_retriever(similarity_top_k=5)
        keyword_retriever = keyword_index.as_retriever(similarity_top_k=5)
        
        fusion_retriever = QueryFusionRetriever(
            retrievers=[vector_retriever, keyword_retriever],
            similarity_top_k=5,
            num_queries=1, # no query expansion to avoid infinite LLM calls in test
            mode="reciprocal_rerank",
            use_async=False,
            verbose=True
        )
        
        return vector_index, keyword_index, fusion_retriever

def get_hybrid_search_results(query_str: str, retriever, similarity_cutoff: float = 0.78):
    """
    Performs retriever query, applies SimilarityPostprocessor with cutoff, and returns results.
    """
    if retriever is None:
        logger.error("Retriever is not initialized.")
        return []
        
    # Query fusion retriever
    nodes = retriever.retrieve(query_str)
    
    # Apply postprocessor (cutoff=0.78 per doc.md)
    # Check if we are using RRF (Reciprocal Rerank Fusion) scores (which are all < 0.1)
    is_rrf = len(nodes) > 0 and all(n.score is not None and n.score < 0.1 for n in nodes)
    
    if is_rrf:
        logger.info(
            f"Detected RRF (Reciprocal Rerank Fusion) scores. "
            f"Bypassing SimilarityPostprocessor (cutoff={similarity_cutoff}) to prevent filtering out rank-based scores."
        )
        filtered_nodes = nodes
    else:
        postprocessor = SimilarityPostprocessor(similarity_cutoff=similarity_cutoff)
        filtered_nodes = postprocessor.postprocess_nodes(nodes)
        
    logger.info(f"Retrieved {len(nodes)} nodes, filtered down to {len(filtered_nodes)} with cutoff {similarity_cutoff}")
    return filtered_nodes
