"""
Tests for the Embedder service.
"""

from unittest.mock import patch, MagicMock
from src.infrastructure.embedder import Embedder


class TestEmbedder:
    """Test embedding service."""

    def test_init_defaults(self) -> None:
        embedder = Embedder(model_name="all-MiniLM-L6-v2", device="cpu")
        assert embedder.model_name == "all-MiniLM-L6-v2"
        assert embedder.device == "cpu"
        assert embedder._model is None
        assert not embedder.is_loaded

    def test_embed_without_model_returns_zeros(self) -> None:
        """When sentence-transformers is not available, return zero vector."""
        embedder = Embedder()

        with patch("src.infrastructure.embedder.Embedder._load_model", return_value=None):
            vector = embedder.embed("test text")
            assert len(vector) == 384
            assert all(v == 0.0 for v in vector)

    def test_embed_batch_without_model(self) -> None:
        embedder = Embedder()

        with patch("src.infrastructure.embedder.Embedder._load_model", return_value=None):
            vectors = embedder.embed_batch(["text1", "text2"])
            assert len(vectors) == 2
            assert all(len(v) == 384 for v in vectors)

    def test_vector_size_default(self) -> None:
        embedder = Embedder()
        assert embedder._vector_size == 384


class TestEmbedderWithModel:
    """Test embedder with a mocked model."""

    def test_embed_with_loaded_model(self) -> None:
        embedder = Embedder()
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock(tolist=MagicMock(return_value=[0.5] * 384))
        embedder._model = mock_model

        vector = embedder.embed("test")
        assert len(vector) == 384
        mock_model.encode.assert_called_once_with("test", normalize_embeddings=True)

    def test_is_loaded(self) -> None:
        embedder = Embedder()
        assert not embedder.is_loaded
        embedder._model = MagicMock()
        assert embedder.is_loaded
