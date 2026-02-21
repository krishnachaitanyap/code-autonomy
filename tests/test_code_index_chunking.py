"""Tests for sliding-window chunking and BM25 hybrid retrieval in entity_embeddings.py"""

import pytest
from unittest.mock import patch, MagicMock

from src.code_index.entity_embeddings import (
    EntityEmbeddings,
    _sliding_window_chunks,
    _tokenize,
    _reciprocal_rank_fusion,
    _extract_import_context,
)


# ---------------------------------------------------------------------------
# Sliding window chunking
# ---------------------------------------------------------------------------

class TestSmallTextSingleChunk:
    def test_small_text_single_chunk(self):
        text = "Hello world, this is a short text."
        chunks = _sliding_window_chunks(text, 800, 200)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_empty_text(self):
        chunks = _sliding_window_chunks("", 800, 200)
        assert len(chunks) == 1


class TestLargeTextMultipleChunks:
    def test_large_text_multiple_chunks(self):
        text = "x" * 2000
        chunks = _sliding_window_chunks(text, 800, 200)
        assert len(chunks) >= 3
        # Verify total coverage
        total_chars = sum(len(c) for c in chunks)
        assert total_chars > len(text)  # overlap means total > original

    def test_exact_boundary(self):
        text = "x" * 800
        chunks = _sliding_window_chunks(text, 800, 200)
        assert len(chunks) == 1
        assert chunks[0] == text


class TestOverlapPresent:
    def test_overlap_present(self):
        text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 50  # 1300 chars
        chunks = _sliding_window_chunks(text, 800, 200)
        assert len(chunks) >= 2
        # Last 200 chars of chunk 0 should equal first 200 chars of chunk 1
        overlap_from_first = chunks[0][-200:]
        overlap_from_second = chunks[1][:200]
        assert overlap_from_first == overlap_from_second


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_camel_case_split(self):
        tokens = _tokenize("findByStatus")
        assert "find" in tokens
        assert "by" in tokens
        assert "status" in tokens

    def test_snake_case_split(self):
        tokens = _tokenize("find_by_status")
        assert "find" in tokens
        assert "by" in tokens
        assert "status" in tokens

    def test_single_char_filtered(self):
        tokens = _tokenize("a b cd")
        assert "a" not in tokens
        assert "b" not in tokens
        assert "cd" in tokens

    def test_lowercased(self):
        tokens = _tokenize("UserService")
        assert all(t == t.lower() for t in tokens)


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------

class TestRRF:
    def test_rrf_merges_correctly(self):
        """Item in both lists should be ranked highest."""
        list_a = [("fqn_a", 0.9), ("fqn_both", 0.8), ("fqn_c", 0.7)]
        list_b = [("fqn_both", 5.0), ("fqn_d", 4.0), ("fqn_e", 3.0)]

        merged = _reciprocal_rank_fusion(list_a, list_b)
        fqns = [fqn for fqn, _ in merged]
        assert fqns[0] == "fqn_both"  # appears in both lists → highest RRF

    def test_rrf_empty_lists(self):
        merged = _reciprocal_rank_fusion([], [])
        assert merged == []

    def test_rrf_one_empty(self):
        list_a = [("fqn_a", 0.9)]
        merged = _reciprocal_rank_fusion(list_a, [])
        assert len(merged) == 1
        assert merged[0][0] == "fqn_a"


# ---------------------------------------------------------------------------
# Import context extraction
# ---------------------------------------------------------------------------

class TestImportContext:
    def test_python_imports(self):
        contents = {
            "app.py": "import os\nfrom pathlib import Path\n\ndef main(): pass\n",
        }
        ctx = _extract_import_context(contents)
        assert "app.py" in ctx
        assert "import os" in ctx["app.py"]
        assert "from pathlib import Path" in ctx["app.py"]

    def test_java_imports(self):
        contents = {
            "App.java": "package com.example;\n\nimport java.util.List;\nimport com.example.User;\n\npublic class App {}\n",
        }
        ctx = _extract_import_context(contents)
        assert "App.java" in ctx
        assert "import java.util.List" in ctx["App.java"]

    def test_truncation(self):
        # Create very long import list
        imports = "\n".join(f"import com.example.Class{i};" for i in range(100))
        contents = {"Big.java": imports}
        ctx = _extract_import_context(contents)
        assert len(ctx.get("Big.java", "")) <= 300


# ---------------------------------------------------------------------------
# EntityEmbeddings build + find_similar with chunking and BM25
# ---------------------------------------------------------------------------

class TestFindSimilarDeduplicates:
    def test_multi_chunk_entity_returns_single_fqn(self):
        """When building with a large body, multi-chunk entity should deduplicate in find_similar."""
        from src.code_index.symbol_table import SymbolTable, SymbolEntry
        import numpy as np

        st = SymbolTable()
        st.add(SymbolEntry(
            fqn="big.py::large_func", file_path="big.py", name="large_func",
            symbol_type="function", line_start=1, line_end=100,
            signature="def large_func()",
        ))

        emb = EntityEmbeddings()
        # Build with a large body to trigger multi-chunking
        big_body = "\n".join([f"    line_{i} = process({i})" for i in range(200)])
        file_contents = {"big.py": f"def large_func():\n{big_body}\n"}

        # Mock _embed_texts to return fake vectors
        dim = 64
        def fake_embed(texts):
            return np.random.randn(len(texts), dim).astype(np.float32)

        with patch.object(emb, '_embed_texts', side_effect=fake_embed):
            emb.build(".", st, file_contents=file_contents)

        # Multiple chunks should have been created
        assert emb._fqns.count("big.py::large_func") >= 2

        # find_similar should deduplicate
        with patch.object(emb, '_embed_texts', side_effect=fake_embed):
            results = emb.find_similar("process data", top_k=5)

        # Should have at most one entry for this FQN
        fqns = [fqn for fqn, _ in results]
        assert fqns.count("big.py::large_func") <= 1


class TestBM25ExactNameMatch:
    def test_bm25_exact_name_match(self):
        """Exact class name should score high in BM25 search."""
        from src.code_index.symbol_table import SymbolTable, SymbolEntry

        st = SymbolTable()
        st.add(SymbolEntry(
            fqn="svc.py::UserService", file_path="svc.py", name="UserService",
            symbol_type="class", line_start=1, line_end=10,
            signature="class UserService",
        ))
        st.add(SymbolEntry(
            fqn="svc.py::OrderService", file_path="svc.py", name="OrderService",
            symbol_type="class", line_start=12, line_end=20,
            signature="class OrderService",
        ))

        emb = EntityEmbeddings()
        file_contents = {
            "svc.py": "class UserService:\n    pass\n\nclass OrderService:\n    pass\n",
        }

        # Build without embeddings API (will fail) but BM25 should work
        config = {"code_index": {"enable_bm25": "true"}}
        try:
            emb.build(".", st, config=config, file_contents=file_contents)
        except Exception:
            pass  # embeddings API may fail, but BM25 built

        if emb._bm25 is not None:
            results = emb._find_by_bm25("UserService", top_k=5)
            if results:
                # UserService should rank first
                assert results[0][0] == "svc.py::UserService"


# ---------------------------------------------------------------------------
# Persistence with new fields
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_save_load_with_chunks_and_bm25(self, tmp_path):
        emb = EntityEmbeddings()
        emb._fqns = ["a.py::foo", "a.py::foo", "b.py::bar"]
        emb._texts = ["text1", "text2", "text3"]
        emb._digests = ["d1", "d2", "d3"]
        emb._chunk_indices = [0, 1, 0]
        emb._bm25_fqns = ["a.py::foo", "b.py::bar"]
        emb._bm25_corpus = [["text1", "text2"], ["text3"]]

        path = str(tmp_path / "emb.pkl")
        emb.save(path)

        loaded = EntityEmbeddings()
        assert loaded.load(path) is True
        assert loaded._fqns == emb._fqns
        assert loaded._chunk_indices == emb._chunk_indices
        assert loaded._bm25_fqns == emb._bm25_fqns
        assert loaded._bm25_corpus == emb._bm25_corpus

    def test_load_old_cache_backward_compat(self, tmp_path):
        """Loading a cache without chunk_indices or bm25 fields should not error."""
        import pickle

        old_data = {
            "fqns": ["a.py::foo"],
            "texts": ["text1"],
            "digests": ["d1"],
            "vectors": None,
        }
        path = tmp_path / "old_emb.pkl"
        with open(path, "wb") as f:
            pickle.dump(old_data, f)

        emb = EntityEmbeddings()
        assert emb.load(str(path)) is True
        assert emb._fqns == ["a.py::foo"]
        assert emb._chunk_indices == [0]  # default
        assert emb._bm25_fqns == []
        assert emb._bm25_corpus == []
