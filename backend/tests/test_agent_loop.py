"""Agent loop behaviour, driven by scripted FakeLLM runs (no network)."""
from app.agent import AgentConfig, EmailInput, FakeLLM, ToolRegistry, run_agent
from app.agent.errors import LLMMalformedOutput, LLMTimeout, LLMTransientError
from app.agent.schemas import LLMResponse, ToolCall

EMAIL = EmailInput(id=1, sender="Sam Lee <sam@example.test>", subject="Server error on login",
                   body="Login is not working since this morning. Please help ASAP. Can you check?")


def call(name, **args):
    return LLMResponse(tool_call=ToolCall(name=name, arguments=args))


GOOD_SCRIPT = lambda: [  # noqa: E731
    call("classify_email", category="support_request", urgency="high"),
    call("extract_tasks", tasks=[{"description": "Check the login failure", "priority": "high"}]),
    call("draft_reply", body="Thanks, we are investigating the login failure now.", tone="formal"),
    LLMResponse(final="Support request, high urgency; reply drafted."),
]


def run(script, cfg=None, **kw):
    reg = ToolRegistry(EMAIL, lambda q, n, ex: [])
    r = run_agent(EMAIL, FakeLLM(script), reg, cfg or AgentConfig(), sleep=kw.pop("sleep", lambda s: None), **kw)
    return r


def test_success_path_collects_everything_and_traces_each_step():
    r = run(GOOD_SCRIPT())
    assert r.ok and r.error_code is None
    assert (r.category, r.urgency) == ("support_request", "high")
    assert [t.description for t in r.tasks] == ["Check the login failure"]
    assert r.draft_body and r.needs_reply
    assert [s.tool for s in r.trace] == ["classify_email", "extract_tasks", "draft_reply", "final"]
    assert all(s.error is None for s in r.trace)
    assert all(s.latency_ms >= 0 for s in r.trace)
    assert r.trace[0].args == {"category": "support_request", "urgency": "high"}


def test_invalid_arguments_are_fed_back_once_then_recover():
    script = [call("classify_email", category="made_up", urgency="high")] + GOOD_SCRIPT()
    llm = FakeLLM(script)
    reg = ToolRegistry(EMAIL, lambda q, n, ex: [])
    r = run_agent(EMAIL, llm, reg, AgentConfig(), sleep=lambda s: None)
    assert r.ok
    assert r.trace[0].tool == "classify_email" and "invalid arguments" in r.trace[0].error
    assert r.trace[1].error is None
    assert reg.state.category == "support_request"


def test_second_invalid_call_fails_safely_with_no_partial_output():
    script = [call("classify_email", category="x", urgency="high"),
              call("classify_email", category="y", urgency="high"),
              call("classify_email", category="support_request", urgency="high")]
    r = run(script)
    assert not r.ok and r.error_code == "invalid_tool_arguments"
    assert r.category is None and r.draft_body is None and r.tasks == []
    assert len(r.trace) == 2  # stopped at the second failure, did not keep looping


def test_unknown_tool_counts_as_invalid_arguments():
    r = run([call("send_email", to="x"), call("send_email", to="x")])
    assert not r.ok and r.error_code == "invalid_tool_arguments"
    assert "unknown tool" in r.trace[0].error


def test_step_cap():
    endless = [call("search_past_emails", query="login")] * 20
    r = run(endless, AgentConfig(max_steps=3))
    assert not r.ok and r.error_code == "step_limit"
    assert len(r.trace) == 3


def test_wall_clock_timeout():
    now = [0.0]

    def clock():
        now[0] += 10.0  # every clock read advances 10s
        return now[0]

    r = run(GOOD_SCRIPT(), AgentConfig(timeout_s=25.0), clock=clock)
    assert not r.ok and r.error_code == "timeout"


def test_tool_error_is_recoverable_once_then_fails():
    # draft before classify => ToolError (recoverable once)
    ok = run([call("draft_reply", body="Premature draft body here."), *GOOD_SCRIPT()])
    assert ok.ok and "classify_email" in ok.trace[0].error

    bad = run([call("draft_reply", body="Premature draft body here."),
               call("draft_reply", body="Premature draft body here.")])
    assert not bad.ok and bad.error_code == "tool_error"


def test_policy_refusal_for_spam_draft():
    script = [call("classify_email", category="spam", urgency="low"),
              call("draft_reply", body="Dear spammer, thanks a lot."),
              LLMResponse(final="spam, no reply")]
    r = run(script)
    assert r.ok and r.draft_body is None and not r.needs_reply
    assert "policy" in r.trace[1].error


def test_llm_timeout_retries_with_capped_backoff_then_succeeds():
    sleeps = []
    script = [LLMTimeout("slow"), LLMTransientError("503"), *GOOD_SCRIPT()]
    r = run(script, AgentConfig(llm_retries=2, backoff_base_s=1.0, backoff_cap_s=1.5), sleep=sleeps.append)
    assert r.ok
    assert sleeps == [1.0, 1.5]  # 1.0, then min(cap, 2.0)
    assert [s.tool for s in r.trace[:2]] == ["llm", "llm"]
    assert "llm_timeout" in r.trace[0].error


def test_llm_timeout_exhausts_retries_and_fails():
    sleeps = []
    r = run([LLMTimeout("slow")] * 5, AgentConfig(llm_retries=2), sleep=sleeps.append)
    assert not r.ok and r.error_code == "llm_timeout"
    assert len(sleeps) == 2  # 3 attempts total


def test_malformed_output_is_not_retried():
    sleeps = []
    r = run([LLMMalformedOutput("garbage"), *GOOD_SCRIPT()], sleep=sleeps.append)
    assert not r.ok and r.error_code == "malformed_output" and sleeps == []


def test_unexpected_provider_exception_never_crashes_the_loop():
    r = run([RuntimeError("boom with secret-ish text")])
    assert not r.ok and r.error_code == "llm_error"
    assert "secret-ish" not in (r.error_message or "")


def test_final_without_classification_is_rejected():
    r = run([LLMResponse(final="all done")])
    assert not r.ok and r.error_code == "no_classification"


def test_empty_response_is_malformed():
    r = run([LLMResponse()])
    assert not r.ok and r.error_code == "malformed_output"


def test_rule_mode_end_to_end():
    reg = ToolRegistry(EMAIL, lambda q, n, ex: [])
    r = run_agent(EMAIL, FakeLLM(), reg, AgentConfig(), sleep=lambda s: None)
    assert r.ok and r.category == "support_request" and r.urgency == "high" and r.needs_reply
