"""
End-to-end integration tests for the Experience Engine.
Tests the full pipeline: create experiences → intercept → get suggestions.

Requires: Engine NOT running (tests start their own TestClient).
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, AsyncMock

from src.main import app
from src.domain.experience_service import ExperienceService
from src.infrastructure.embedder import Embedder


@pytest.fixture
def e2e_client() -> TestClient:
    """Create an end-to-end test client with real embedder but mocked Qdrant/LLM."""
    qdrant = MagicMock()
    embedder = MagicMock()
    llm = AsyncMock()

    # Setup realistic defaults
    qdrant.is_healthy.return_value = True
    qdrant.count.return_value = 0
    qdrant.search.return_value = []
    qdrant.list_experiences.return_value = []
    qdrant.get_experience.return_value = None
    embedder.is_loaded = True
    embedder.embed.return_value = [0.1] * 384
    embedder.vector_size = 384

    service = ExperienceService(qdrant=qdrant, embedder=embedder, llm=llm)
    app.state.service = service

    return TestClient(app)


class TestE2EHealthFlow:
    """Test the full health check flow."""

    def test_health_returns_all_fields(self, e2e_client: TestClient) -> None:
        resp = e2e_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "qdrant" in data
        assert "embedder_loaded" in data
        assert "llm_available" in data
        assert "uptime_seconds" in data
        assert "version" in data
        assert data["status"] == "ok"
        assert data["version"] == "0.2.0"

    def test_ready_endpoint(self, e2e_client: TestClient) -> None:
        resp = e2e_client.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is True

    def test_stats_endpoint(self, e2e_client: TestClient) -> None:
        resp = e2e_client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_experiences"] == 0
        assert data["total_queries"] == 0
        assert data["avg_latency_ms"] == 0.0


class TestE2EInterceptFlow:
    """Test the full intercept pipeline flow."""

    def test_readonly_action_returns_instantly(self, e2e_client: TestClient) -> None:
        """Layer 1: Read-only actions should be skipped with 0ms latency."""
        readonly_actions = [
            {"action": "cat README.md", "action_type": "read"},
            {"action": "git status", "action_type": "unknown"},
            {"action": "ls src/", "action_type": "unknown"},
            {"action": "git log --oneline", "action_type": "unknown"},
            {"action": "view_file main.py", "action_type": "unknown"},
        ]

        for payload in readonly_actions:
            resp = e2e_client.post("/api/intercept", json=payload)
            assert resp.status_code == 200
            data = resp.json()
            assert data["skipped"] is True, f"Expected {payload['action']} to be skipped"
            assert data["latency_ms"] == 0.0
            assert "L1" in data["layers_executed"]

    def test_write_action_triggers_pipeline(self, e2e_client: TestClient) -> None:
        """Write actions should pass through Layer 1 and hit Layer 2."""
        resp = e2e_client.post("/api/intercept", json={
            "action": "edit file db.ts",
            "action_type": "write",
            "file_path": "src/db.ts",
            "language": "typescript",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["skipped"] is False
        assert "L1" in data["layers_executed"]
        assert "L2" in data["layers_executed"]

    def test_unknown_action_type_not_readonly(self, e2e_client: TestClient) -> None:
        """Unknown actions that don't match readonly patterns should go through pipeline."""
        resp = e2e_client.post("/api/intercept", json={
            "action": "create new database migration",
            "action_type": "unknown",
        })
        data = resp.json()
        assert data["skipped"] is False

    def test_intercept_with_suggestions(self, e2e_client: TestClient) -> None:
        """When Qdrant returns results and LLM filters, suggestions should be returned."""
        service = app.state.service

        # Mock Qdrant to return results
        service.qdrant.search.return_value = [
            {
                "payload": {
                    "id": "exp-singleton",
                    "title": "Use Singleton for DB",
                    "description": "Always use singleton pattern for database connections",
                    "severity": "warning",
                    "category": "pattern",
                },
                "score": 0.92,
            },
            {
                "payload": {
                    "id": "exp-pool",
                    "title": "Use Connection Pooling",
                    "description": "Use connection pooling for better performance",
                    "severity": "info",
                    "category": "performance",
                },
                "score": 0.78,
            },
        ]

        # Mock LLM to keep only the first result
        service.llm.filter_experiences = AsyncMock(return_value=["exp-singleton"])

        resp = e2e_client.post("/api/intercept", json={
            "action": "create database connection in db.ts",
            "action_type": "write",
            "file_path": "src/db.ts",
        })
        data = resp.json()

        assert data["skipped"] is False
        assert len(data["suggestions"]) == 1
        assert data["suggestions"][0]["title"] == "Use Singleton for DB"
        assert data["suggestions"][0]["relevance_score"] == 0.92
        assert data["suggestions"][0]["source"] == "llm_filter"
        assert "L3" in data["layers_executed"]
        assert data["latency_ms"] >= 0


class TestE2EExperienceCRUD:
    """Test the full experience CRUD flow."""

    def test_create_experience(self, e2e_client: TestClient) -> None:
        """Create a new experience and verify it was stored."""
        resp = e2e_client.post("/api/experiences", json={
            "title": "Use Singleton for DB",
            "description": "Always use singleton pattern for database connections to avoid resource leaks",
            "category": "pattern",
            "severity": "warning",
            "tags": ["database", "singleton"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Use Singleton for DB"
        assert data["category"] == "pattern"
        assert data["severity"] == "warning"
        assert "database" in data["tags"]
        assert data["id"]  # UUID generated

        # Verify qdrant was called
        app.state.service.qdrant.upsert_experience.assert_called()
        app.state.service.embedder.embed.assert_called()

    def test_list_experiences_empty(self, e2e_client: TestClient) -> None:
        resp = e2e_client.get("/api/experiences")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_get_experience_not_found(self, e2e_client: TestClient) -> None:
        resp = e2e_client.get("/api/experiences/nonexistent-id")
        assert resp.status_code == 404

    def test_delete_experience_not_found(self, e2e_client: TestClient) -> None:
        app.state.service.qdrant.delete_experience.side_effect = Exception("Not found")
        resp = e2e_client.delete("/api/experiences/nonexistent-id")
        assert resp.status_code == 404

    def test_feedback_not_found(self, e2e_client: TestClient) -> None:
        resp = e2e_client.post("/api/experiences/nonexistent-id/feedback", json={
            "score": 1.0,
            "comment": "Great suggestion!",
        })
        assert resp.status_code == 404


class TestE2EOpenAPI:
    """Test OpenAPI/Swagger documentation is available."""

    def test_openapi_json(self, e2e_client: TestClient) -> None:
        resp = e2e_client.get("/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["info"]["title"] == "Loomind Experience Engine"
        assert data["info"]["version"] == "0.2.0"

        # Check all expected paths exist
        paths = data["paths"]
        assert "/api/intercept" in paths
        assert "/api/experiences" in paths
        assert "/health" in paths
        assert "/ready" in paths
        assert "/api/stats" in paths

    def test_docs_page(self, e2e_client: TestClient) -> None:
        resp = e2e_client.get("/docs")
        assert resp.status_code == 200
        assert "swagger" in resp.text.lower() or "openapi" in resp.text.lower()
