import os
import shutil
import tempfile
import pytest
from fastapi import HTTPException
from unittest.mock import patch

# Mock settings before importing app modules
import app.ai_models.rag as rag

@pytest.fixture(autouse=True)
def setup_teardown_test_db():
    # Setup temporary directory for test DB
    test_db_dir = tempfile.mkdtemp()
    
    # Save original globals
    orig_client = rag._client
    orig_collection = rag._collection
    orig_encoder = rag._encoder
    orig_cache = rag._bm25_cache.copy()
    orig_hashes = rag._indexed_hashes.copy()
    orig_path = rag.CHROMA_DB_PATH
    
    # Reset globals for tests
    rag._client = None
    rag._collection = None
    rag._encoder = None
    rag._invalidate_bm25_cache()
    rag._indexed_hashes.clear()
    rag.CHROMA_DB_PATH = test_db_dir
    
    yield
    
    # Cleanup directory
    shutil.rmtree(test_db_dir, ignore_errors=True)
    
    # Restore original globals
    rag._client = orig_client
    rag._collection = orig_collection
    rag._encoder = orig_encoder
    rag._bm25_cache = orig_cache
    rag._indexed_hashes = orig_hashes
    rag.CHROMA_DB_PATH = orig_path


def test_lazy_loading_and_empty_check():
    """Verify that collection can be retrieved and empty checks happen without loading the encoder."""
    assert rag._client is None
    assert rag._collection is None
    assert rag._encoder is None

    # Get collection
    col = rag._get_collection()
    assert col is not None
    assert rag._client is not None
    assert rag._collection is not None
    # Encoder MUST NOT be loaded yet!
    assert rag._encoder is None

    # auto_rag_context should return None immediately because count is 0, without loading encoder
    context = rag.auto_rag_context("Hello world")
    assert context is None
    assert rag._encoder is None


def test_indexing_and_bm25_cache_invalidation():
    """Verify that indexing documents builds and invalidates the BM25 cache correctly."""
    col = rag._get_collection()
    
    # Initially cache is empty
    cache = rag._get_bm25_index(col)
    assert cache is None

    # Index first document
    doc1 = b"Python is a high-level general-purpose programming language."
    rag._index_document(doc1, "python_doc.txt")
    
    # Cache should be invalidated (index is None) but get_bm25_index will rebuild it
    assert rag._bm25_cache["index"] is None
    
    cache = rag._get_bm25_index(col)
    assert cache is not None
    assert cache["last_count"] == 1
    assert len(cache["docs"]) == 1
    assert "python" in cache["docs"][0].lower()

    # Index second document
    doc2 = b"Vite JS is a fast build tool for modern web development."
    rag._index_document(doc2, "vite_doc.txt")

    # Cache must be invalidated again after indexing
    assert rag._bm25_cache["index"] is None
    
    cache = rag._get_bm25_index(col)
    assert cache is not None
    assert cache["last_count"] == 2
    assert len(cache["docs"]) == 2


def test_auto_rag_context_filtering():
    """Verify that auto_rag_context uses BM25 to filter out queries with zero keyword matches."""
    col = rag._get_collection()
    
    doc = b"The stock market saw dynamic volatility today."
    rag._index_document(doc, "market.txt")
    
    # 1. Non-matching query (should return None immediately without encoding)
    # Let's mock _get_encoder to verify it is NOT called
    with patch("app.ai_models.rag._get_encoder") as mock_get_encoder:
        context = rag.auto_rag_context("Python programming language")
        assert context is None
        mock_get_encoder.assert_not_called()

    # 2. Matching query (should load encoder and run vector validation)
    # The default distance threshold is 0.3, so let's check if it calls the encoder
    with patch("app.ai_models.rag._get_encoder") as mock_get_encoder:
        # Mock encoder's encode behavior
        mock_encoder = mock_get_encoder.return_value
        mock_encoder.encode.return_value.tolist.return_value = [0.0] * 384
        
        # We also need to mock collection.query to return distances
        with patch.object(col, "query") as mock_query:
            mock_query.return_value = {
                "documents": [["The stock market saw dynamic volatility today."]],
                "distances": [[0.1]],
                "metadatas": [[{"source": "market.txt", "file_type": "Text"}]]
            }
            
            context = rag.auto_rag_context("stock market volatility")
            assert context is not None
            assert "stock market" in context
            mock_get_encoder.assert_called_once()


@pytest.mark.asyncio
async def test_search_endpoint_methods():
    """Verify the /search endpoint supports different methods (bm25, dense, hybrid)."""
    col = rag._get_collection()
    
    doc1 = b"We are learning Python for artificial intelligence."
    doc2 = b"Vite and React are tools for building user interfaces."
    
    rag._index_document(doc1, "ai.txt")
    rag._index_document(doc2, "ui.txt")

    # Test pure BM25 search
    results = await rag.search("Python learning", hybrid=False, method="bm25")
    assert results["method"] == "bm25"
    assert len(results["documents"]) == 1
    assert "Python" in results["documents"][0]

    # Test pure dense search
    with patch("app.ai_models.rag._get_encoder") as mock_get_encoder:
        mock_encoder = mock_get_encoder.return_value
        mock_encoder.encode.return_value.tolist.return_value = [0.0] * 384
        
        with patch.object(col, "query") as mock_query:
            mock_query.return_value = {
                "documents": [["We are learning Python for artificial intelligence."]],
                "metadatas": [[{"source": "ai.txt"}]]
            }
            
            results = await rag.search("Python learning", method="dense")
            assert results["method"] == "dense"
            assert len(results["documents"]) == 1
            assert "Python" in results["documents"][0]

    # Test hybrid search
    with patch("app.ai_models.rag._get_encoder") as mock_get_encoder:
        mock_encoder = mock_get_encoder.return_value
        mock_encoder.encode.return_value.tolist.return_value = [0.0] * 384
        
        with patch.object(col, "query") as mock_query:
            mock_query.return_value = {
                "documents": [["We are learning Python for artificial intelligence."]],
                "metadatas": [[{"source": "ai.txt"}]],
                "distances": [[0.2]]
            }
            
            results = await rag.search("Python learning", method="hybrid")
            assert results["method"] == "hybrid"
            assert len(results["documents"]) > 0
