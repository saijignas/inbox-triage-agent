"""Provider layer. The Gemini tests use a stub client: no key, no network."""
import pytest

from app.agent.errors import LLMMalformedOutput, LLMTimeout, LLMTransientError
from app.agent.providers import FakeLLM, GeminiLLM, analyze_email, format_email_prompt
from app.agent.schemas import LLMResponse, Message, ToolCall, ToolSpec


def test_fake_rule_mode_is_deterministic():
    msgs = [Message(role="system", content="s"),
            Message(role="user", content=format_email_prompt("a@example.test", "Hello", "Are you free for a meeting tomorrow?"))]
    a, b = FakeLLM().generate(msgs, []), FakeLLM().generate(msgs, [])
    assert a == b and a.tool_call.name == "search_past_emails"


def test_analyze_email_rules():
    spam = analyze_email("x@example.test", "You have won!", "Click here to claim your free gift. URGENT")
    assert spam["category"] == "spam" and spam["urgency"] == "low" and not spam["wants_reply"]
    mtg = analyze_email("Ana <a@example.test>", "Meeting?", "Can we schedule a call tomorrow? Let me know.")
    assert mtg["category"] == "meeting_request" and mtg["urgency"] == "medium" and mtg["wants_reply"]
    assert mtg["first_name"] == "Ana"


def test_fake_scripted_mode_raises_scripted_exceptions():
    llm = FakeLLM([LLMTimeout("t"), LLMResponse(final="ok")])
    with pytest.raises(LLMTimeout):
        llm.generate([], [])
    assert llm.generate([], []).final == "ok"
    assert llm.generate([], []).final == "script exhausted"


def test_gemini_requires_key_when_no_client(monkeypatch):
    with pytest.raises(ValueError):
        GeminiLLM(api_key=None)


genai = pytest.importorskip("google.genai", reason="optional dependency")
from google.genai import errors, types  # noqa: E402


class _StubModels:
    def __init__(self, outcome):
        self.outcome, self.last = outcome, None

    def generate_content(self, model, contents, config):
        self.last = {"model": model, "contents": contents, "config": config}
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _StubClient:
    def __init__(self, outcome):
        self.models = _StubModels(outcome)


def _response(part):
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[part]))])


TOOLS = [ToolSpec(name="classify_email", description="d", parameters={"type": "object", "properties": {"category": {"type": "string"}}})]
MSGS = [
    Message(role="system", content="sys"),
    Message(role="user", content="hello"),
    Message(role="assistant", tool_call=ToolCall(name="search_past_emails", arguments={"query": "q"})),
    Message(role="tool", tool_name="search_past_emails", content='{"matches": []}'),
    Message(role="tool", tool_name="classify_email", content="bad args", is_error=True),
]


def test_gemini_translates_history_tools_and_config():
    stub = _StubClient(_response(types.Part.from_function_call(name="classify_email", args={"category": "spam", "urgency": "low"})))
    out = GeminiLLM(api_key="k", client=stub).generate(MSGS, TOOLS, timeout_s=7)
    assert out.tool_call.name == "classify_email" and out.tool_call.arguments["category"] == "spam"
    sent = stub.models.last
    assert sent["config"].system_instruction == "sys"
    assert sent["config"].automatic_function_calling.disable is True  # our loop, not the SDK's
    assert sent["config"].http_options.timeout == 7000
    assert sent["config"].tools[0].function_declarations[0].name == "classify_email"
    roles = [c.role for c in sent["contents"]]
    assert roles == ["user", "model", "user", "user"]
    assert sent["contents"][3].parts[0].function_response.response == {"error": "bad args"}


def test_gemini_parses_final_text():
    out = GeminiLLM(api_key="k", client=_StubClient(_response(types.Part.from_text(text="  done  ")))).generate(MSGS, TOOLS)
    assert out.final == "done" and out.tool_call is None


def test_gemini_empty_response_is_malformed():
    with pytest.raises(LLMMalformedOutput):
        GeminiLLM(api_key="k", client=_StubClient(types.GenerateContentResponse(candidates=[]))).generate(MSGS, TOOLS)


@pytest.mark.parametrize("code,exc", [(429, LLMTransientError), (503, LLMTransientError), (504, LLMTimeout)])
def test_gemini_maps_api_errors(code, exc):
    err = errors.APIError(code, {"error": {"message": "bad key-123 here"}})
    llm = GeminiLLM(api_key="key-123", client=_StubClient(err))
    with pytest.raises(exc) as info:
        llm.generate(MSGS, TOOLS)
    assert "key-123" not in str(info.value)  # key scrubbed from messages


def test_gemini_thought_signature_is_replayed_verbatim():
    """Regression: newer Gemini models reject a function call echoed back without its
    thought signature (HTTP 400). The original part must be kept and replayed unchanged."""
    part = types.Part(
        function_call=types.FunctionCall(name="classify_email", args={"category": "billing", "urgency": "high"}),
        thought_signature=b"sig-123",
    )

    class _Content:
        parts = [part]

    class _Cand:
        content = _Content()

    class _Resp:
        candidates = [_Cand()]

    parsed = GeminiLLM._parse(_Resp())
    assert parsed.tool_call.name == "classify_email"
    assert parsed.tool_call.provider_state is part
    # provider_state must never leak into serialized traces/records
    assert "provider_state" not in parsed.tool_call.model_dump()

    system, contents = GeminiLLM._to_contents([
        Message(role="system", content="s"),
        Message(role="user", content="hi"),
        Message(role="assistant", tool_call=parsed.tool_call),
    ])
    replayed = contents[-1].parts[0]
    assert replayed.thought_signature == b"sig-123"
    assert replayed.function_call.name == "classify_email"
