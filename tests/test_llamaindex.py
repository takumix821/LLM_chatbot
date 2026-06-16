import os
import pytest
from llama_index.core.schema import Document

from ingestion import extract_shopee_article_metadata, IngestionPipeline, get_hybrid_search_results
import config

def test_extract_shopee_article_metadata():
    """Test Shopee Metadata extraction from raw text via regex."""
    sample_text = (
        "Article URL: https://seller.shopee.tw/edu/article/101\n"
        "Article Title: 蝦皮賣家成交手續費與金流服務費收取機制\n"
        "Category: 平台費用與撥款\n"
        "Sub-Category: 手續費規範\n"
        "\n"
        "=== CONTENT BODY ===\n"
        "成交手續費是單件商品售價百分之五點五。如果重複刊登或延遲出貨會被扣分。"
    )
    
    metadata = extract_shopee_article_metadata(sample_text)
    
    assert metadata["url"] == "https://seller.shopee.tw/edu/article/101"
    assert metadata["title"] == "蝦皮賣家成交手續費與金流服務費收取機制"
    assert metadata["category"] == "平台費用與撥款"
    assert metadata["sub_category"] == "手續費規範"
    assert "手續費/費用" in metadata["tags"]
    assert "計分/違規" in metadata["tags"]
    assert "免運/物流" not in metadata["tags"]

def test_ingestion_pipeline_run(tmp_path):
    """Test the complete LlamaIndex ingestion pipeline execution for Shopee articles."""
    # 1. Clear database table to isolate this test case
    conn = config.get_database_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM segmented_nodes")
    conn.commit()
    conn.close()

    # Write a temporary mock article file
    mock_dir = tmp_path / "mock_data"
    mock_dir.mkdir()
    mock_file = mock_dir / "test_article.txt"
    mock_file.write_text(
        "Article URL: https://seller.shopee.tw/edu/article/102\n"
        "Article Title: 賣家計分系統與違規罰分處置說明\n"
        "Category: 賣場管理與規範\n"
        "Sub-Category: 計分系統\n"
        "\n"
        "=== CONTENT BODY ===\n"
        "蝦皮賣家違規罰分每週一更新。單週延遲出貨率高於十趴會被扣一分。"
    )
    
    # Initialize pipeline with mock directory and force re-indexing
    pipeline = IngestionPipeline(data_dir=str(mock_dir))
    vector_index, keyword_index, fusion_retriever = pipeline.run_pipeline(force_reindex=True)
    
    # Check that indices were built successfully
    assert vector_index is not None
    assert keyword_index is not None
    assert fusion_retriever is not None
    
    # Query hybrid search
    query = "延遲出貨扣幾分？"
    results = get_hybrid_search_results(query, fusion_retriever, similarity_cutoff=0.0)
    
    # Verify retrieval outputs
    assert len(results) > 0
    node = results[0]
    
    # Verify metadata is retained on nodes
    assert node.node.metadata["url"] == "https://seller.shopee.tw/edu/article/102"
    assert node.node.metadata["title"] == "賣家計分系統與違規罰分處置說明"
    assert node.node.metadata["category"] == "賣場管理與規範"
    
    # Verify sentence window metadata is present
    assert "window" in node.node.metadata
    assert len(node.node.metadata["window"]) > 0

def test_similarity_postprocessor_filter():
    """Test that similarity postprocessor correctly filters out nodes below cutoff."""
    from llama_index.core.schema import NodeWithScore, TextNode
    from llama_index.core.postprocessor import SimilarityPostprocessor
    
    nodes = [
        NodeWithScore(node=TextNode(text="High score node"), score=0.95),
        NodeWithScore(node=TextNode(text="Low score node"), score=0.50),
    ]
    
    postprocessor = SimilarityPostprocessor(similarity_cutoff=0.78)
    filtered = postprocessor.postprocess_nodes(nodes)
    
    assert len(filtered) == 1
    assert filtered[0].node.text == "High score node"

def test_sqlite_node_persistence(tmp_path):
    """Test saving to and loading from the SQLite segmented_nodes table."""
    # Write a temporary mock report file
    mock_dir = tmp_path / "mock_data"
    mock_dir.mkdir()
    mock_file = mock_dir / "test_article.txt"
    mock_file.write_text(
        "Article URL: https://seller.shopee.tw/edu/article/103\n"
        "Article Title: 免運專案合約說明\n"
        "Category: 行銷推廣\n"
        "Sub-Category: 免運活動\n"
        "\n"
        "=== CONTENT BODY ===\n"
        "免運專案加收三趴至五趴服務費。"
    )
    
    # 1. Clear database table to start fresh
    conn = config.get_database_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM segmented_nodes")
    conn.commit()
    
    # Check count is 0
    cursor.execute("SELECT COUNT(*) FROM segmented_nodes")
    assert cursor.fetchone()[0] == 0
    conn.close()
    
    # 2. Run pipeline to process, embed, and save to SQLite
    pipeline = IngestionPipeline(data_dir=str(mock_dir))
    vector_index, keyword_index, fusion_retriever = pipeline.run_pipeline(force_reindex=True)
    
    assert vector_index is not None
    
    # Check count in DB is now greater than 0
    conn = config.get_database_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM segmented_nodes")
    count_after = cursor.fetchone()[0]
    assert count_after > 0
    conn.close()
    
    # 3. Load from DB (force_reindex=False)
    pipeline2 = IngestionPipeline(data_dir=str(mock_dir))
    vector_index2, keyword_index2, fusion_retriever2 = pipeline2.run_pipeline(force_reindex=False)
    
    assert vector_index2 is not None
    # Verify that query works
    results = get_hybrid_search_results("免運專案", fusion_retriever2, similarity_cutoff=0.0)
    assert len(results) > 0
    assert results[0].node.metadata["title"] == "免運專案合約說明"
