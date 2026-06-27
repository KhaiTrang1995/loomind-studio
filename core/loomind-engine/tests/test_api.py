"""
Integration tests for FastAPI endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, AsyncMock

from src.main import app
from src.domain.experience_service import ExperienceService


@pytest.fixture
def client() -> TestClient:
    """Create a test client with mocked service."""
    qdrant = MagicMock()
    embedder = MagicMock()
    llm = AsyncMock()

    # Setup defaults
    qdrant.is_healthy.return_value = True
    qdrant.count.return_value = 0
    qdrant.search.return_value = []
    embedder.is_loaded = True
    embedder.embed.return_value = [0.0] * 384
    embedder.vector_size = 384

    service = ExperienceService(qdrant=qdrant, embedder=embedder, llm=llm)
    app.state.service = service

    return TestClient(app)


class TestRootEndpoint:
    def test_root(self, client: TestClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Loomind Experience Engine"


class TestHealthEndpoints:
    def test_health(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["qdrant"] is True

    def test_ready(self, client: TestClient) -> None:
        resp = client.get("/ready")
        assert resp.status_code == 200

    def test_stats(self, client: TestClient) -> None:
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_experiences" in data


class TestInterceptEndpoint:
    def test_intercept_readonly(self, client: TestClient) -> None:
        resp = client.post("/api/intercept", json={
            "action": "cat README.md",
            "action_type": "read",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["skipped"] is True

    def test_intercept_write(self, client: TestClient) -> None:
        resp = client.post("/api/intercept", json={
            "action": "edit file db.ts",
            "action_type": "write",
            "file_path": "src/db.ts",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["skipped"] is False
        assert "layers_executed" in data


class TestExperienceEndpoints:
    def test_list_empty(self, client: TestClient) -> None:
        # Mock list
        app.state.service.qdrant.list_experiences.return_value = []
        app.state.service.qdrant.count.return_value = 0

        resp = client.get("/api/experiences")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []
