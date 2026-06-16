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

def extract_shopee_article_metadata(text: str) -> dict:
    """
    Extracts Shopee article metadata from document text using regular expressions.
    Fields to extract: URL, Title, Category, Sub-Category, Tags.
    """
    metadata = {}
    
    # Regex patterns for metadata extraction
    patterns = {
        "url": r"Article URL:\s*(.*)",
        "title": r"Article Title:\s*(.*)",
        "category": r"Category:\s*(.*)",
        "sub_category": r"Sub-Category:\s*(.*)"
    }
    
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            metadata[key] = match.group(1).strip()
            
    # Look for key tags in the text
    tags = []
    if "手續費" in text or "費率" in text or "費用" in text:
        tags.append("手續費/費用")
    if "罰分" in text or "計分" in text or "違規" in text or "扣分" in text:
        tags.append("計分/違規")
    if "免運" in text or "運費" in text:
        tags.append("免運/物流")
    if "上架" in text or "重覆刊登" in text or "重複刊登" in text or "醫療器材" in text:
        tags.append("上架規範")
    if "聊聊" in text or "顧客" in text:
        tags.append("聊聊與客服")
        
    if tags:
        metadata["tags"] = tags
        
    return metadata

class IngestionPipeline:
    def __init__(self, data_dir: str = "mock_data"):
        self.data_dir = data_dir
        self.embed_model = config.get_llamaindex_embedding()
        self.llm = config.get_llamaindex_llm()
        
        # Configure global settings for LlamaIndex
        Settings.embed_model = self.embed_model
        Settings.llm = self.llm
        
    def run_pipeline(self, force_reindex: bool = False):
        """
        Executes the ingestion pipeline:
        1. If force_reindex is False, checks if nodes exist in SQLite segmented_nodes table.
           If they do, loads nodes from the DB, reconstructs TextNode objects, and builds indexes.
        2. Otherwise, loads documents from directory, applies SemanticSplitterNodeParser,
           applies SentenceWindowNodeParser, extracts SEC metadata, calculates embeddings,
           saves to SQLite DB, and builds indexes.
        Returns (vector_index, keyword_index, retriever)
        """
        logger.info(f"Starting Ingestion Pipeline. Directory: {self.data_dir}, force_reindex: {force_reindex}")
        
        final_nodes = []
        loaded_from_db = False
        
        if not force_reindex:
            try:
                conn = config.get_database_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM segmented_nodes")
                row = cursor.fetchone()
                count = row[0] if row is not None else 0
                if count > 0:
                    logger.info(f"Found {count} segmented nodes in database. Loading...")
                    cursor.execute("SELECT node_id, file_name, text_content, embedding_vector, metadata_json FROM segmented_nodes")
                    rows = cursor.fetchall()
                    
                    import json
                    from llama_index.core.schema import TextNode
                    
                    for row in rows:
                        node_id, file_name, text_content, embedding_vector, metadata_json = row
                        try:
                            embedding = json.loads(embedding_vector)
                        except Exception:
                            embedding = None
                        try:
                            metadata = json.loads(metadata_json)
                        except Exception:
                            metadata = {}
                            
                        node = TextNode(
                            text=text_content,
                            id_=node_id,
                            embedding=embedding,
                            metadata=metadata
                        )
                        final_nodes.append(node)
                    loaded_from_db = True
                    logger.info(f"Successfully loaded {len(final_nodes)} nodes from database.")
                conn.close()
            except Exception as e:
                logger.warning(f"Failed to load nodes from database: {e}. Falling back to parsing documents.")
                final_nodes = []
                
        if not loaded_from_db:
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
                extracted = extract_shopee_article_metadata(doc.text)
                doc.metadata.update(extracted)
                logger.info(f"Extracted document metadata: {doc.metadata}")
                
            # 2. Semantic Node Parser
            semantic_parser = SemanticSplitterNodeParser(
                buffer_size=1, 
                breakpoint_percentile_threshold=95,
                embed_model=self.embed_model
            )
            
            # 3. Sentence Window Parser
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
            
            logger.info(f"Successfully processed {len(documents)} document(s) into {len(final_nodes)} sentence-window nodes. Generating embeddings...")
            
            # Generate embeddings
            for node in final_nodes:
                if node.embedding is None:
                    try:
                        node.embedding = self.embed_model.get_text_embedding(node.get_content(metadata_mode="embed"))
                    except Exception as e:
                        logger.warning(f"Failed to generate embedding for node {node.node_id}: {e}")
                
            # Save to database
            import json
            conn = config.get_database_connection()
            
            if hasattr(conn, "client"):  # GCP BigQuery Connection
                try:
                    cursor = conn.cursor()
                    node_ids = [node.node_id for node in final_nodes]
                    logger.info(f"Batch deleting {len(node_ids)} existing nodes from BigQuery...")
                    # Delete in chunks of 500 to stay within query limits
                    for i in range(0, len(node_ids), 500):
                        chunk = node_ids[i:i+500]
                        placeholders = ",".join(["?"] * len(chunk))
                        cursor.execute(f"DELETE FROM segmented_nodes WHERE node_id IN ({placeholders})", chunk)
                    
                    # Prepare rows for streaming insert
                    table_id = f"{conn.client.project}.{conn.dataset_name}.segmented_nodes"
                    rows_to_insert = []
                    for node in final_nodes:
                        file_name = node.metadata.get("file_name") or os.path.basename(node.metadata.get("file_path", "unknown"))
                        embedding_vector = json.dumps(node.embedding) if node.embedding is not None else "[]"
                        metadata_json = json.dumps(node.metadata)
                        rows_to_insert.append({
                            "node_id": node.node_id,
                            "file_name": file_name,
                            "text_content": node.text,
                            "embedding_vector": embedding_vector,
                            "metadata_json": metadata_json
                        })
                    logger.info(f"Batch inserting {len(rows_to_insert)} nodes to BigQuery...")
                    errors = conn.client.insert_rows_json(table_id, rows_to_insert)
                    if errors:
                        logger.error(f"Failed to batch insert rows to BigQuery: {errors}")
                        raise RuntimeError(f"BigQuery batch insert failed: {errors}")
                    else:
                        logger.info(f"Successfully batch saved {len(final_nodes)} segmented nodes to BigQuery.")
                except Exception as e:
                    logger.error(f"Failed to execute batch operations on BigQuery: {e}. Falling back to row-by-row execute.")
                    # Fallback row-by-row on BigQuery just in case
                    cursor = conn.cursor()
                    for node in final_nodes:
                        file_name = node.metadata.get("file_name") or os.path.basename(node.metadata.get("file_path", "unknown"))
                        embedding_vector = json.dumps(node.embedding) if node.embedding is not None else "[]"
                        metadata_json = json.dumps(node.metadata)
                        cursor.execute("DELETE FROM segmented_nodes WHERE node_id = ?", (node.node_id,))
                        cursor.execute(
                            "INSERT INTO segmented_nodes (node_id, file_name, text_content, embedding_vector, metadata_json) VALUES (?, ?, ?, ?, ?)",
                            (node.node_id, file_name, node.text, embedding_vector, metadata_json)
                        )
            else:  # SQLite Connection
                cursor = conn.cursor()
                for node in final_nodes:
                    file_name = node.metadata.get("file_name") or os.path.basename(node.metadata.get("file_path", "unknown"))
                    embedding_vector = json.dumps(node.embedding) if node.embedding is not None else "[]"
                    metadata_json = json.dumps(node.metadata)
                    cursor.execute("DELETE FROM segmented_nodes WHERE node_id = ?", (node.node_id,))
                    cursor.execute(
                        "INSERT INTO segmented_nodes (node_id, file_name, text_content, embedding_vector, metadata_json) VALUES (?, ?, ?, ?, ?)",
                        (node.node_id, file_name, node.text, embedding_vector, metadata_json)
                    )
                conn.commit()
                logger.info(f"Successfully saved {len(final_nodes)} segmented nodes to SQLite database.")
            
            conn.close()
            
        if not final_nodes:
            logger.warning("No nodes available to build indices.")
            return None, None, None
            
        # 4. Build indices
        logger.info("Building VectorStoreIndex...")
        vector_index = VectorStoreIndex(final_nodes)
        
        logger.info("Building SimpleKeywordTableIndex...")
        keyword_index = SimpleKeywordTableIndex(final_nodes)
        
        # 5. Create hybrid retriever using QueryFusionRetriever with Reciprocal Rerank Fusion (RRF)
        vector_retriever = vector_index.as_retriever(similarity_top_k=5)
        keyword_retriever = keyword_index.as_retriever(similarity_top_k=5)
        
        fusion_retriever = QueryFusionRetriever(
            retrievers=[vector_retriever, keyword_retriever],
            similarity_top_k=5,
            num_queries=1,
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
