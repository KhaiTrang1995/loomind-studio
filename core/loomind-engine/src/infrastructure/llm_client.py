"""
LLM Client for the Anti-Noise Filter (Layer 3).
Calls Ollama or llama.cpp to filter irrelevant experiences.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ==================== Filter Prompt ====================

FILTER_PROMPT_TEMPLATE = """You are an AI experience judge. Given a list of past experiences and a current developer action, determine which experiences are TRULY relevant to the current action.

CURRENT ACTION: "{action}"
FILE: "{file_path}"

EXPERIENCES:
{experiences_text}

Return ONLY a JSON object with the IDs of relevant experiences:
{{"relevant_ids": ["id1", "id2"]}}

Rules:
- Only include experiences that are directly applicable to the current action and file.
- If none are relevant, return {{"relevant_ids": []}}
- Do NOT include experiences about unrelated topics.
"""


class LLMClient:
    """Client for calling local LLMs (Ollama or llama.cpp) for anti-noise filtering."""

    def __init__(self, provider: str = "ollama", url: str = "http://localhost:11434", model: str = "llama3.2:3b") -> None:
        self.provider = provider
        self.url = url.rstrip("/")
        self.model = model
        self.http = httpx.AsyncClient(timeout=30.0)

    async def filter_experiences(
        self,
        experiences: list[dict[str, Any]],
        action: str,
        file_path: str | None = None,
    ) -> list[str]:
        """Ask the LLM which experiences are relevant to the current action.

        Returns a list of relevant experience IDs.
        """
        if not experiences:
            return []

        # Build the experiences text
        exp_lines = []
        for i, exp in enumerate(experiences, 1):
            payload = exp.get("payload", exp)
            exp_id = payload.get("id", f"exp_{i}")
            title = payload.get("title", "Untitled")
            desc = payload.get("description", "")
            exp_lines.append(f"{i}. [{exp_id}] {title}: {desc[:200]}")

        prompt = FILTER_PROMPT_TEMPLATE.format(
            action=action,
            file_path=file_path or "unknown",
            experiences_text="\n".join(exp_lines),
        )

        try:
            response_text = await self._call_llm(prompt)
            return self._parse_relevant_ids(response_text, experiences)
        except Exception:
            logger.exception("LLM filter failed, returning all experience IDs as fallback")
            return [exp.get("payload", exp).get("id", "") for exp in experiences]

    async def _call_llm(self, prompt: str) -> str:
        """Route to the appropriate LLM provider."""
        if self.provider == "ollama":
            return await self._call_ollama(prompt)
        elif self.provider == "llamacpp":
            return await self._call_llamacpp(prompt)
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")

    async def _call_ollama(self, prompt: str) -> str:
        """Call Ollama API /api/generate."""
        url = f"{self.url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        resp = await self.http.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")

    async def _call_llamacpp(self, prompt: str) -> str:
        """Call llama.cpp OpenAI-compatible API."""
        url = f"{self.url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        resp = await self.http.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def _parse_relevant_ids(self, response_text: str, experiences: list[dict[str, Any]]) -> list[str]:
        """Parse the LLM response to extract relevant experience IDs."""
        try:
            # Try to parse as JSON
            data = json.loads(response_text)
            ids = data.get("relevant_ids", [])
            # Validate IDs exist in our experience list
            valid_ids = {exp.get("payload", exp).get("id", "") for exp in experiences}
            return [eid for eid in ids if eid in valid_ids]
        except (json.JSONDecodeError, KeyError):
            logger.warning("Failed to parse LLM response as JSON: %s", response_text[:200])
            # Fallback: return all
            return [exp.get("payload", exp).get("id", "") for exp in experiences]

    async def complete(self, prompt: str, *, json_mode: bool = True) -> str:
        """Send a free-form prompt to the LLM and return the raw response text.

        Used by services that need ad-hoc LLM calls (judge, evolution, extraction,
        contradiction detection, etc.) rather than the templated filter pipeline.

        Args:
            prompt: The full prompt string to send.
            json_mode: When True (default), instructs the provider to return JSON.

        Returns:
            The model's response text. Caller is responsible for JSON parsing.

        Raises:
            httpx.HTTPError or ValueError on transport/provider failure.
        """
        if self.provider == "ollama":
            url = f"{self.url}/api/generate"
            payload: dict[str, Any] = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
            }
            if json_mode:
                payload["format"] = "json"
            resp = await self.http.post(url, json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "")

        if self.provider == "llamacpp":
            url = f"{self.url}/v1/chat/completions"
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            resp = await self.http.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

        raise ValueError(f"Unknown LLM provider: {self.provider}")

    async def is_available(self) -> bool:
        """Check if the LLM provider is reachable."""
        try:
            if self.provider == "ollama":
                resp = await self.http.get(f"{self.url}/api/tags", timeout=3.0)
                return resp.status_code == 200
            elif self.provider == "llamacpp":
                resp = await self.http.get(f"{self.url}/health", timeout=3.0)
                return resp.status_code == 200
        except Exception:
            pass
        return False

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.http.aclose()
