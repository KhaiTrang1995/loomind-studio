"""
Tests for the Experience Service — 3-layer intercept pipeline.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.domain.models import ActionType, InterceptRequest
from src.domain.experience_service import ExperienceService


class TestReadonlyFilter:
    """Test Layer 1: Read-only filter."""

    @pytest.fixture
    def service(self) -> ExperienceService:
        qdrant = MagicMock()
        embedder = MagicMock()
        llm = MagicMock()
        return ExperienceService(qdrant=qdrant, embedder=embedder, llm=llm)

    @pytest.mark.asyncio
    async def test_readonly_action_skipped(self, service: ExperienceService) -> None:
        req = InterceptRequest(action="cat README.md", action_type=ActionType.READ)
        resp = await service.intercept(req)
        assert resp.skipped is True
        assert resp.latency_ms == 0.0
        assert "L1" in resp.layers_executed

    @pytest.mark.asyncio
    async def test_readonly_pattern_detected(self, service: ExperienceService) -> None:
        req = InterceptRequest(action="git log --oneline")
        resp = await service.intercept(req)
        assert resp.skipped is True

    @pytest.mark.asyncio
    async def test_write_action_not_skipped(self, service: ExperienceService) -> None:
        # Setup mocks for Layer 2 (no results)
        service.embedder.embed = MagicMock(return_value=[0.0] * 384)
        service.qdrant.search = MagicMock(return_value=[])

        req = InterceptRequest(action="edit file db.ts", action_type=ActionType.WRITE)
        resp = await service.intercept(req)
        assert resp.skipped is False
        assert "L1" in resp.layers_executed
        assert "L2" in resp.layers_executed


class TestSemanticSearch:
    """Test Layer 2: Semantic search."""

    @pytest.mark.asyncio
    async def test_returns_suggestions_when_found(self) -> None:
        qdrant = MagicMock()
        embedder = MagicMock()
        llm = AsyncMock()

        embedder.embed = MagicMock(return_value=[0.1] * 384)
        qdrant.search = MagicMock(return_value=[
            {
                "payload": {
                    "id": "exp-1",
                    "title": "Use Singleton",
                    "description": "Always use singleton for DB connections",
                    "severity": "warning",
                },
                "score": 0.85,
            }
        ])
        llm.filter_experiences = AsyncMock(return_value=["exp-1"])

        service = ExperienceService(qdrant=qdrant, embedder=embedder, llm=llm)
        req = InterceptRequest(action="create database connection in db.ts")
        resp = await service.intercept(req)

        assert resp.skipped is False
        assert len(resp.suggestions) == 1
        assert resp.suggestions[0].title == "Use Singleton"
        assert "L2" in resp.layers_executed
        assert "L3" in resp.layers_executed

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        qdrant = MagicMock()
        embedder = MagicMock()
        llm = MagicMock()

        embedder.embed = MagicMock(return_value=[0.0] * 384)
        qdrant.search = MagicMock(return_value=[])

        service = ExperienceService(qdrant=qdrant, embedder=embedder, llm=llm)
        req = InterceptRequest(action="edit something.py")
        resp = await service.intercept(req)

        assert resp.skipped is False
        assert len(resp.suggestions) == 0
