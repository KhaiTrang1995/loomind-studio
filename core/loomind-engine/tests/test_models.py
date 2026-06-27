"""
Tests for domain models.
"""

from src.domain.models import (
    ActionType,
    CreateExperienceRequest,
    Experience,
    InterceptRequest,
    InterceptResponse,
    Severity,
    Suggestion,
)


class TestInterceptRequest:
    def test_defaults(self) -> None:
        req = InterceptRequest(action="edit file db.ts")
        assert req.action == "edit file db.ts"
        assert req.action_type == ActionType.UNKNOWN
        assert req.file_path is None

    def test_full_request(self) -> None:
        req = InterceptRequest(
            action="edit file db.ts",
            action_type=ActionType.WRITE,
            file_path="src/db.ts",
            language="typescript",
            agent="copilot",
        )
        assert req.action_type == ActionType.WRITE
        assert req.file_path == "src/db.ts"


class TestExperience:
    def test_defaults(self) -> None:
        exp = Experience(title="Test", description="A test experience")
        assert exp.title == "Test"
        assert exp.severity == Severity.INFO
        assert exp.usage_count == 0
        assert exp.feedback_score == 0.0
        assert exp.id  # UUID auto-generated

    def test_create_request(self) -> None:
        req = CreateExperienceRequest(
            title="Use Singleton",
            description="Always use singleton for DB connections",
            category="pattern",
            tags=["database", "singleton"],
            severity=Severity.WARNING,
        )
        assert req.category == "pattern"
        assert "database" in req.tags


class TestInterceptResponse:
    def test_skipped(self) -> None:
        resp = InterceptResponse(skipped=True, latency_ms=0.0, layers_executed=["L1"])
        assert resp.skipped
        assert len(resp.suggestions) == 0

    def test_with_suggestions(self) -> None:
        resp = InterceptResponse(
            skipped=False,
            suggestions=[
                Suggestion(
                    experience_id="abc",
                    title="Use Singleton",
                    message="Remember to use singleton pattern",
                    severity=Severity.WARNING,
                    relevance_score=0.85,
                )
            ],
            latency_ms=42.5,
            layers_executed=["L1", "L2", "L3"],
        )
        assert len(resp.suggestions) == 1
        assert resp.suggestions[0].relevance_score == 0.85
        assert resp.latency_ms == 42.5
