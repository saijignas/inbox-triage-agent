"""Schemas and tool-argument validation."""
import pytest
from pydantic import ValidationError

from app.agent.errors import ToolError
from app.agent.schemas import (
    ClassifyEmailArgs, DraftReplyArgs, EmailInput, ExtractTasksArgs, SearchPastEmailsArgs,
)
from app.agent.tools import ToolRegistry, UnknownTool

EMAIL = EmailInput(id=1, sender="a@example.test", subject="Hi", body="Body text here")


def make_registry(search=lambda q, n, ex: []):
    return ToolRegistry(EMAIL, search)


def test_classify_accepts_valid_values():
    a = ClassifyEmailArgs(category="billing", urgency="high")
    assert a.category == "billing"


@pytest.mark.parametrize("bad", [
    {"category": "nonsense", "urgency": "high"},
    {"category": "billing", "urgency": "extreme"},
    {"category": "billing"},
    {"category": "billing", "urgency": "low", "extra": 1},  # extra fields forbidden
])
def test_classify_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        ClassifyEmailArgs(**bad)


def test_extract_tasks_limits():
    with pytest.raises(ValidationError):
        ExtractTasksArgs(tasks=[{"description": "ok task"}] * 11)
    with pytest.raises(ValidationError):
        ExtractTasksArgs(tasks=[{"description": "x"}])  # too short
    assert ExtractTasksArgs(tasks=[]).tasks == []


def test_search_and_draft_arg_bounds():
    with pytest.raises(ValidationError):
        SearchPastEmailsArgs(query="a")
    with pytest.raises(ValidationError):
        DraftReplyArgs(body="short", tone="formal")
    with pytest.raises(ValidationError):
        DraftReplyArgs(body="x" * 4001)
    with pytest.raises(ValidationError):
        DraftReplyArgs(body="long enough body", tone="sarcastic")


def test_registry_specs_expose_all_four_tools_with_json_schema():
    specs = {s.name: s for s in make_registry().specs()}
    assert set(specs) == {"classify_email", "extract_tasks", "search_past_emails", "draft_reply"}
    assert specs["classify_email"].parameters["properties"]["category"]["enum"]


def test_registry_validates_before_running():
    reg = make_registry()
    with pytest.raises(ValidationError):
        reg.execute("classify_email", {"category": "bogus", "urgency": "low"})
    assert reg.state.category is None  # handler never ran


def test_unknown_tool():
    with pytest.raises(UnknownTool):
        make_registry().execute("send_email", {})


def test_classify_then_draft_records_state():
    reg = make_registry()
    reg.execute("classify_email", {"category": "support_request", "urgency": "medium"})
    out = reg.execute("draft_reply", {"body": "Thanks, looking into it now.", "tone": "formal"})
    assert out["queued_for_approval"] is True
    assert reg.state.draft_body.startswith("Thanks")


def test_draft_requires_classification_first():
    with pytest.raises(ToolError):
        make_registry().execute("draft_reply", {"body": "Thanks, looking into it now."})


@pytest.mark.parametrize("cat", ["spam", "newsletter"])
def test_draft_refused_for_no_reply_categories(cat):
    reg = make_registry()
    reg.execute("classify_email", {"category": cat, "urgency": "low"})
    with pytest.raises(ToolError, match="policy"):
        reg.execute("draft_reply", {"body": "Thanks for the message."})
    assert reg.state.draft_body is None


def test_search_tool_passes_current_email_id_for_exclusion():
    seen = {}

    def search(q, n, ex):
        seen.update(q=q, n=n, ex=ex)
        return [{"id": 9, "subject": "old"}]

    out = make_registry(search).execute("search_past_emails", {"query": "invoice"})
    assert seen == {"q": "invoice", "n": 3, "ex": 1}
    assert out["matches"][0]["id"] == 9
