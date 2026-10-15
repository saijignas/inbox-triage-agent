"""Failure taxonomy. Each maps to a stable `error_code` stored with the triage result."""
from __future__ import annotations


class LLMError(Exception):
    code = "llm_error"


class LLMTimeout(LLMError):
    """Provider call timed out. Retryable with capped backoff."""

    code = "llm_timeout"


class LLMTransientError(LLMError):
    """Rate limit / 5xx / network blip. Retryable with capped backoff."""

    code = "llm_unavailable"


class LLMMalformedOutput(LLMError):
    """Model output could not be interpreted at all (not even as a tool call). Not retried."""

    code = "malformed_output"


class ToolError(Exception):
    """A tool refused or failed. Recoverable once: reported to the model as an observation."""
