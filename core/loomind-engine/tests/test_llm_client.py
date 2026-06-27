"""
Tests for the LLM Client.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.infrastructure.llm_client import LLMClient


class TestLLMClient:
    """Test LLM anti-noise filter client."""

    def test_init(self) -> None:
        client = LLMClient(provider="ollama", url="http://localhost:11434", model="llama3.2:3b")
        assert client.provider == "ollama"
        assert client.url == "http://localhost:11434"
        assert client.model == "llama3.2:3b"

    @pytest.mark.asyncio
    async def test_filter_empty_experiences(self) -> None:
        client = LLMClient()
        result = await client.filter_experiences([], "edit db.ts")
        assert result == []

    def test_parse_valid_json(self) -> None:
        client = LLMClient()
        experiences = [
            {"payload": {"id": "exp-1", "title": "Test 1"}},
            {"payload": {"id": "exp-2", "title": "Test 2"}},
        ]
        response = json.dumps({"relevant_ids": ["exp-1"]})
        result = client._parse_relevant_ids(response, experiences)
        assert result == ["exp-1"]

    def test_parse_invalid_json_returns_all(self) -> None:
        client = LLMClient()
        experiences = [
            {"payload": {"id": "exp-1"}},
            {"payload": {"id": "exp-2"}},
        ]
        result = client._parse_relevant_ids("not json", experiences)
        assert len(result) == 2  # Fallback: return all IDs

    def test_parse_filters_invalid_ids(self) -> None:
        client = LLMClient()
        experiences = [{"payload": {"id": "exp-1"}}]
        response = json.dumps({"relevant_ids": ["exp-1", "exp-nonexistent"]})
        result = client._parse_relevant_ids(response, experiences)
        assert result == ["exp-1"]  # Only valid IDs


class TestLLMClientAvailability:
    @pytest.mark.asyncio
    async def test_is_available_false_when_unreachable(self) -> None:
        client = LLMClient(url="http://localhost:99999")
        result = await client.is_available()
        assert result is False
        await client.close()
