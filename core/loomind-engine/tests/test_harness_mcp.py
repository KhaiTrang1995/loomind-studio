import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.domain.models import Experience, Suggestion, InterceptResponse
from src.presentation.mcp_server import intercept_action, add_experience, search_experiences, get_stats, get_health
from src.client import LoomindClient

@pytest.mark.asyncio
async def test_mcp_intercept_action() -> None:
    mock_response = InterceptResponse(
        skipped=False,
        suggestions=[
            Suggestion(
                experience_id="exp-1",
                title="Test Experience",
                message="Test Description",
                severity="warning",
                relevance_score=0.9,
                source="llm_filter"
            )
        ],
        latency_ms=10.0,
        layers_executed=["L1", "L2", "L3"]
    )

    with patch("src.presentation.mcp_server.get_service") as mock_get_service:
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.intercept = AsyncMock(return_value=mock_response)

        res_str = await intercept_action(action="test action", action_type="write")
        assert "Test Experience" in res_str
        assert "exp-1" in res_str
        assert "skipped" in res_str

def test_mcp_add_experience() -> None:
    mock_exp = Experience(
        id="exp-uuid",
        title="New Experience",
        description="New Desc",
        category="pattern",
        tags=["test"],
        severity="info"
    )

    with patch("src.presentation.mcp_server.get_service") as mock_get_service:
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.create_experience.return_value = mock_exp

        res_str = add_experience(title="New Experience", description="New Desc", category="pattern")
        assert "New Experience" in res_str
        assert "exp-uuid" in res_str

def test_mcp_search_experiences() -> None:
    mock_exp = Experience(
        id="exp-uuid",
        title="Searched Experience",
        description="Searched Desc",
        category="pattern",
        tags=["test"],
        severity="info"
    )

    with patch("src.presentation.mcp_server.get_service") as mock_get_service:
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.search_experiences.return_value = [mock_exp]

        res_str = search_experiences(query="test query")
        assert "Searched Experience" in res_str
        assert "exp-uuid" in res_str

def test_mcp_get_stats() -> None:
    with patch("src.presentation.mcp_server.get_service") as mock_get_service:
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.total_queries = 42
        mock_service.avg_latency_ms = 12.3

        res_str = get_stats()
        assert "42" in res_str
        assert "12.3" in res_str

@pytest.mark.asyncio
async def test_mcp_get_health() -> None:
    with patch("src.presentation.mcp_server.get_service") as mock_get_service, \
         patch("src.presentation.mcp_server._qdrant") as mock_qdrant, \
         patch("src.presentation.mcp_server._llm") as mock_llm, \
         patch("src.presentation.mcp_server._embedder") as mock_embedder:

        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_qdrant.is_healthy.return_value = True
        mock_llm.is_available = AsyncMock(return_value=True)
        mock_embedder.is_loaded = True

        res_str = await get_health()
        assert "ok" in res_str
        assert "true" in res_str

def test_client_is_healthy() -> None:
    client = LoomindClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok"}

    with patch.object(client.client, "get", return_value=mock_response):
        assert client.is_healthy() is True

def test_client_intercept() -> None:
    client = LoomindClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"skipped": True, "suggestions": []}

    with patch.object(client.client, "post", return_value=mock_response):
        res = client.intercept(action="cat file", action_type="read")
        assert res["skipped"] is True
