import os
import pytest
from llama_index.core.schema import Document

from ingestion import extract_sec_metadata, IngestionPipeline, get_hybrid_search_results
import config

def test_extract_sec_metadata():
    """Test SEC Metadata extraction from raw text via regex."""
    sample_text = (
        "====== AAPL FY2024Q1 Financial Report Summary ======\n"
        "Company Code: AAPL\n"
        "Fiscal Year: 2024\n"
        "Quarter: Q1\n"
        "Document Type: SEC Form 10-Q\n"
        "Revenue is $119,575 million and Capex is $2,912 million."
    )
    
    metadata = extract_sec_metadata(sample_text)
    
    assert metadata["company_code"] == "AAPL"
    assert metadata["fiscal_year"] == "2024"
    assert metadata["quarter"] == "Q1"
    assert metadata["doc_type"] == "SEC Form 10-Q"
    assert "Revenue" in metadata["important_metrics"]
    assert "Capex" in metadata["important_metrics"]
    assert "Gross Margin" not in metadata["important_metrics"]

def test_ingestion_pipeline_run(tmp_path):
    """Test the complete LlamaIndex ingestion pipeline execution."""
    # 1. Clear database table to isolate this test case
    conn = config.get_database_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM segmented_nodes")
    conn.commit()
    conn.close()

    # Write a temporary mock report file
    mock_dir = tmp_path / "mock_data"
    mock_dir.mkdir()
    mock_file = mock_dir / "test_report.txt"
    mock_file.write_text(
        "Company Code: AAPL\n"
        "Fiscal Year: 2024\n"
        "Quarter: Q1\n"
        "Document Type: SEC Form 10-Q\n"
        "Apple net income was high. iPhone sales were outstanding.\n"
        "The overall revenue reached a staggering amount. Gross Margin was 45.9%.\n"
        "Capital expenditure Capex is controlled."
    )
    
    # Initialize pipeline with mock directory and force re-indexing
    pipeline = IngestionPipeline(data_dir=str(mock_dir))
    vector_index, keyword_index, fusion_retriever = pipeline.run_pipeline(force_reindex=True)
    
    # Check that indices were built successfully
    assert vector_index is not None
    assert keyword_index is not None
    assert fusion_retriever is not None
    
    # Query hybrid search
    query = "What is the Gross Margin for AAPL in 2024Q1?"
    results = get_hybrid_search_results(query, fusion_retriever, similarity_cutoff=0.0) # set 0.0 to retrieve all nodes in local mock
    
    # Verify retrieval outputs
    assert len(results) > 0
    node = results[0]
    
    # Verify metadata is retained on nodes
    assert node.node.metadata["company_code"] == "AAPL"
    assert node.node.metadata["fiscal_year"] == "2024"
    assert node.node.metadata["quarter"] == "Q1"
    
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
    mock_file = mock_dir / "test_report.txt"
    mock_file.write_text(
        "Company Code: AAPL\n"
        "Fiscal Year: 2024\n"
        "Quarter: Q1\n"
        "Document Type: SEC Form 10-Q\n"
        "Apple net income was high. iPhone sales were outstanding.\n"
        "The overall revenue reached a staggering amount. Gross Margin was 45.9%.\n"
        "Capital expenditure Capex is controlled."
    )
    
    # 1. Clear database table to start fresh
    import sqlite3
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
    # The pipeline should read from SQLite instead of parsing files again
    pipeline2 = IngestionPipeline(data_dir=str(mock_dir))
    vector_index2, keyword_index2, fusion_retriever2 = pipeline2.run_pipeline(force_reindex=False)
    
    assert vector_index2 is not None
    # Verify that query works
    results = get_hybrid_search_results("Gross Margin", fusion_retriever2, similarity_cutoff=0.0)
    assert len(results) > 0
    assert results[0].node.metadata["company_code"] == "AAPL"
