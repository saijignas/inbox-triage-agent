"""The agent loop: plan -> call tool -> observe -> repeat, until a final answer or a limit.

Guarantees (each covered by tests):
  * hard cap on steps and on wall-clock time;
  * every tool argument is validated by Pydantic before the tool runs;
  * invalid arguments / unknown tool / tool refusal are fed back to the model ONCE per run
    (`recoverable_error_budget`); a second one fails the run safely;
  * provider timeouts and transient errors are retried with capped exponential backoff;
  * malformed provider output is not retried;
  * the loop never raises: it always returns an `AgentRun` with a trace;
  * a failed run returns no category/tasks/draft, so nothing half-baked can be persisted.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import ValidationError

from .errors import LLMError, LLMMalformedOutput, LLMTimeout, LLMTransientError, ToolError
from .providers import SYSTEM_PROMPT, LLMProvider, format_email_prompt
from .schemas import AgentRun, EmailInput, LLMResponse, Message, ToolCall, TraceStep
from .tools import ToolRegistry, UnknownTool


@dataclass(frozen=True)
class AgentConfig:
    max_steps: int = 8
    timeout_s: float = 30.0  # wall-clock budget for the whole run
    llm_call_timeout_s: float = 20.0  # per provider call (also capped by remaining budget)
    llm_retries: int = 2  # retries after the first attempt, for timeouts/transient errors
    backoff_base_s: float = 0.5
    backoff_cap_s: float = 4.0
    recoverable_error_budget: int = 1


class _Fail(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _validation_summary(e: ValidationError) -> str:
    # Field paths + messages only; never echo the offending input value back.
    return "; ".join(f"{'.'.join(str(p) for p in err['loc']) or 'arguments'}: {err['msg']}" for err in e.errors()[:5])


def run_agent(
    email: EmailInput,
    provider: LLMProvider,
    registry: ToolRegistry,
    config: AgentConfig | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> AgentRun:
    cfg = config or AgentConfig()
    sleep = sleep or time.sleep  # resolved at call time so tests can patch it
    trace: list[TraceStep] = []
    messages = [
        Message(role="system", content=SYSTEM_PROMPT),
        Message(role="user", content=format_email_prompt(email.sender, email.subject, email.body)),
    ]
    specs = registry.specs()
    start = clock()
    budget = cfg.recoverable_error_budget

    def remaining() -> float:
        return cfg.timeout_s - (clock() - start)

    def fail(code: str, message: str) -> AgentRun:
        return AgentRun(ok=False, error_code=code, error_message=message[:500], trace=trace)

    def call_llm(step: int) -> LLMResponse:
        attempt = 0
        while True:
            left = remaining()
            if left <= 0:
                raise _Fail("timeout", f"run exceeded {cfg.timeout_s}s budget")
            t0 = clock()
            try:
                return provider.generate(messages, specs, min(cfg.llm_call_timeout_s, left))
            except (LLMTimeout, LLMTransientError) as e:
                trace.append(TraceStep(step=step, tool="llm", error=f"{e.code}: {e}", latency_ms=(clock() - t0) * 1000))
                if attempt >= cfg.llm_retries:
                    raise _Fail(e.code, f"{e} (gave up after {attempt + 1} attempts)")
                sleep(min(cfg.backoff_cap_s, cfg.backoff_base_s * (2**attempt)))
                attempt += 1
            except LLMMalformedOutput as e:
                trace.append(TraceStep(step=step, tool="llm", error=f"{e.code}: {e}", latency_ms=(clock() - t0) * 1000))
                raise _Fail(e.code, str(e))
            except LLMError as e:
                trace.append(TraceStep(step=step, tool="llm", error=f"{e.code}: {e}", latency_ms=(clock() - t0) * 1000))
                raise _Fail(e.code, str(e))
            except Exception as e:  # a buggy provider must not crash the worker
                trace.append(TraceStep(step=step, tool="llm", error=f"unexpected {type(e).__name__}", latency_ms=(clock() - t0) * 1000))
                raise _Fail("llm_error", f"unexpected provider failure: {type(e).__name__}")

    try:
        for step in range(1, cfg.max_steps + 1):
            resp = call_llm(step)

            if resp.tool_call is None:
                final = (resp.final or "").strip()
                if not final:
                    raise _Fail("malformed_output", "model returned neither a tool call nor a final answer")
                state = registry.state
                if state.category is None or state.urgency is None:
                    raise _Fail("no_classification", "model finished without calling classify_email")
                trace.append(TraceStep(step=step, tool="final", result=final[:500]))
                return AgentRun(
                    ok=True,
                    category=state.category,
                    urgency=state.urgency,
                    tasks=state.tasks,
                    draft_body=state.draft_body,
                    draft_tone=state.draft_tone,
                    summary=final[:500],
                    trace=trace,
                )

            call: ToolCall = resp.tool_call
            messages.append(Message(role="assistant", tool_call=call))
            t0 = clock()
            result: dict[str, Any] | None = None
            error: str | None = None
            error_code = "tool_error"
            try:
                result = registry.execute(call.name, call.arguments)
            except ValidationError as e:
                error, error_code = f"invalid arguments for {call.name}: {_validation_summary(e)}", "invalid_tool_arguments"
            except UnknownTool as e:
                error, error_code = str(e), "invalid_tool_arguments"
            except ToolError as e:
                error, error_code = f"{call.name} failed: {e}", "tool_error"
            except Exception as e:  # tool bug: treat like a tool error, don't leak internals
                error, error_code = f"{call.name} crashed ({type(e).__name__})", "tool_error"
            latency = (clock() - t0) * 1000
            trace.append(TraceStep(step=step, tool=call.name, args=call.arguments, result=result, error=error, latency_ms=latency))

            if error is None:
                messages.append(Message(role="tool", tool_name=call.name, content=json.dumps(result, default=str)))
                continue
            if budget > 0:
                budget -= 1
                messages.append(Message(role="tool", tool_name=call.name, content=error, is_error=True))
                continue
            raise _Fail(error_code, error)

        raise _Fail("step_limit", f"no final answer within {cfg.max_steps} steps")
    except _Fail as f:
        return fail(f.code, f.message)
