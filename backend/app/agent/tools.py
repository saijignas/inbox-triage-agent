"""The four agent tools. Arguments are validated with Pydantic before a handler runs.

Tools never touch the database writes for triage output: they record into an in-memory
`RunState`. The service layer persists the final state in one transaction, so a failed
run leaves no half-written drafts or tasks behind.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel

from .errors import ToolError
from .schemas import (
    NO_REPLY_CATEGORIES,
    ClassifyEmailArgs,
    DraftReplyArgs,
    EmailInput,
    ExtractTasksArgs,
    SearchPastEmailsArgs,
    TaskItem,
    ToolSpec,
)

# search(query, limit, exclude_email_id) -> [{"id", "sender", "subject", "snippet"}, ...]
SearchFn = Callable[[str, int, int | None], list[dict[str, Any]]]


@dataclass
class RunState:
    category: str | None = None
    urgency: str | None = None
    tasks: list[TaskItem] = field(default_factory=list)
    tasks_extracted: bool = False
    draft_body: str | None = None
    draft_tone: str | None = None


class UnknownTool(Exception):
    pass


@dataclass
class _Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[Any], dict[str, Any]]


class ToolRegistry:
    def __init__(self, email: EmailInput, search_fn: SearchFn, state: RunState | None = None):
        self.email = email
        self.state = state or RunState()
        self._search = search_fn
        self._tools: dict[str, _Tool] = {}
        for t in (
            _Tool(
                "classify_email",
                "Record the category and urgency of the email. Call exactly once.",
                ClassifyEmailArgs,
                self._classify,
            ),
            _Tool(
                "extract_tasks",
                "Record the action items the recipient must do. Pass an empty list if there are none.",
                ExtractTasksArgs,
                self._extract,
            ),
            _Tool(
                "search_past_emails",
                "Search previously stored emails by keyword to get context. Read-only.",
                SearchPastEmailsArgs,
                self._search_past,
            ),
            _Tool(
                "draft_reply",
                "Write a reply DRAFT. It is queued for human approval and is never sent. "
                "Only call when a reply is needed; classify_email must be called first.",
                DraftReplyArgs,
                self._draft,
            ),
        ):
            self._tools[t.name] = t

    # -- public --------------------------------------------------------------------------

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(name=t.name, description=t.description, parameters=t.args_model.model_json_schema())
            for t in self._tools.values()
        ]

    def names(self) -> list[str]:
        return list(self._tools)

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Validate arguments then run the tool.

        Raises UnknownTool, pydantic.ValidationError (bad args) or ToolError (tool refused).
        """
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownTool(f"unknown tool '{name}'; available: {', '.join(self._tools)}")
        args = tool.args_model.model_validate(arguments)  # raises ValidationError
        return tool.handler(args)

    # -- handlers ------------------------------------------------------------------------

    def _classify(self, a: ClassifyEmailArgs) -> dict[str, Any]:
        self.state.category = a.category
        self.state.urgency = a.urgency
        return {"category": a.category, "urgency": a.urgency}

    def _extract(self, a: ExtractTasksArgs) -> dict[str, Any]:
        self.state.tasks = list(a.tasks)
        self.state.tasks_extracted = True
        return {"count": len(a.tasks)}

    def _search_past(self, a: SearchPastEmailsArgs) -> dict[str, Any]:
        hits = self._search(a.query, 3, self.email.id)
        return {"query": a.query, "matches": hits}

    def _draft(self, a: DraftReplyArgs) -> dict[str, Any]:
        if self.state.category is None:
            raise ToolError("call classify_email before draft_reply")
        if self.state.category in NO_REPLY_CATEGORIES:
            raise ToolError(f"policy: no replies are drafted for category '{self.state.category}'")
        self.state.draft_body = a.body
        self.state.draft_tone = a.tone
        return {"queued_for_approval": True, "chars": len(a.body)}
