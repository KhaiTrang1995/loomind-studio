"""
Embedding service using Sentence-Transformers.
Provides text → vector encoding for semantic search.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class Embedder:
    """Lazy-loaded Sentence-Transformers embedder.

    The model is loaded on first use and cached as a singleton.
    Default model: all-MiniLM-L6-v2 (384 dimensions, fast, lightweight).
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", device: str = "cpu") -> None:
        self.model_name = model_name
        self.device = device
        self._model: Optional[object] = None
        self._vector_size: int = 384  # default for MiniLM

    def _load_model(self) -> object:
        """Load the Sentence-Transformers model (lazy, first-call only)."""
        if self._model is None:
            logger.info("Loading embedding model '%s' on device '%s'...", self.model_name, self.device)
            start = time.monotonic()
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self.model_name, device=self.device)
                self._vector_size = self._model.get_sentence_embedding_dimension()  # type: ignore[union-attr]
                elapsed = (time.monotonic() - start) * 1000
                logger.info("Model loaded in %.1fms (vector_size=%d)", elapsed, self._vector_size)
            except ImportError:
                logger.warning("sentence-transformers not installed, using dummy embeddings")
                self._model = None
            except Exception:
                logger.exception("Failed to load embedding model")
                self._model = None
        return self._model  # type: ignore[return-value]

    def embed(self, text: str) -> list[float]:
        """Encode a single text string into a vector."""
        model = self._load_model()
        if model is None:
            # Return a dummy zero vector when model is unavailable
            return [0.0] * self._vector_size

        start = time.monotonic()
        vector = model.encode(text, normalize_embeddings=True).tolist()  # type: ignore[union-attr]
        elapsed = (time.monotonic() - start) * 1000
        logger.debug("Embedded text (%.1fms): %s...", elapsed, text[:50])
        return vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts into vectors."""
        model = self._load_model()
        if model is None:
            return [[0.0] * self._vector_size for _ in texts]

        vectors = model.encode(texts, normalize_embeddings=True).tolist()  # type: ignore[union-attr]
        return vectors

    @property
    def vector_size(self) -> int:
        """Dimensionality of the output vectors."""
        self._load_model()
        return self._vector_size

    @property
    def is_loaded(self) -> bool:
        """Whether the model has been loaded."""
        return self._model is not None
