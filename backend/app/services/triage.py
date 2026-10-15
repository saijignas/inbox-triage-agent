"""Triage orchestration: idempotent claiming, background execution, atomic persistence.

Idempotency: one `triage_results` row per email (UNIQUE email_id) and one `drafts` row per email
(UNIQUE email_id). `claim_triage` is a compare-and-set, so two concurrent requests for the same
email can never both start a run, and a repeat request after completion is a no-op.

Known gap: a process crash while status == 'running' leaves the row stuck; there is no lease/
heartbeat recovery yet (see README "Limitations").
"""
from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ..agent import AgentConfig, EmailInput, LLMProvider, ToolRegistry, run_agent
from ..agent.schemas import AgentRun
from ..models import Draft, DraftStatus, Email, Task, TriageResult, TriageStatus
from .emails import search_emails

log = logging.getLogger("triage")


def claim_triage(db: Session, email_id: int) -> tuple[TriageResult, bool]:
    """Return (result_row, claimed). claimed=True means the caller must schedule the run."""
    result = db.scalar(select(TriageResult).where(TriageResult.email_id == email_id))
    if result is None:
        try:
            result = TriageResult(email_id=email_id, status=TriageStatus.queued, trace=[])
            db.add(result)
            db.commit()
            return result, True
        except IntegrityError:  # lost a race with a concurrent request
            db.rollback()
            result = db.scalar(select(TriageResult).where(TriageResult.email_id == email_id))
            assert result is not None
            return result, False
    if result.status == TriageStatus.failed:
        res = db.execute(
            update(TriageResult)
            .where(TriageResult.id == result.id, TriageResult.status == TriageStatus.failed)
            .values(status=TriageStatus.queued, error_code=None, error_message=None)
        )
        db.commit()
        db.refresh(result)
        return result, res.rowcount == 1
    return result, False  # queued / running / completed -> nothing to do


def _persist(db: Session, result: TriageResult, email_id: int, run: AgentRun, provider_name: str) -> None:
    """Write the outcome in ONE transaction. A failed run writes only the error + trace."""
    result.trace = [s.model_dump(mode="json") for s in run.trace]
    result.provider = provider_name
    if run.ok:
        result.status = TriageStatus.completed
        result.category, result.urgency = run.category, run.urgency
        result.needs_reply = run.needs_reply
        result.summary = run.summary
        result.error_code = result.error_message = None
        for old in db.scalars(select(Task).where(Task.email_id == email_id)):
            db.delete(old)
        for t in run.tasks:
            db.add(Task(email_id=email_id, description=t.description, due_hint=t.due_hint, priority=t.priority))
        if run.draft_body is not None and db.scalar(select(Draft.id).where(Draft.email_id == email_id)) is None:
            try:
                with db.begin_nested():
                    db.add(Draft(email_id=email_id, body=run.draft_body, tone=run.draft_tone or "formal",
                                 status=DraftStatus.pending))
            except IntegrityError:
                pass  # another worker created the draft first: exactly one draft per email
    else:
        result.status = TriageStatus.failed
        result.error_code, result.error_message = run.error_code, run.error_message
    db.commit()


def _mark_failed(db: Session, email_id: int, code: str, message: str) -> None:
    db.rollback()
    db.execute(
        update(TriageResult)
        .where(TriageResult.email_id == email_id)
        .values(status=TriageStatus.failed, error_code=code, error_message=message[:500])
    )
    db.commit()


def run_triage_job(
    session_factory: sessionmaker[Session],
    provider_factory: Callable[[], LLMProvider],
    email_id: int,
    config: AgentConfig | None = None,
) -> None:
    """Background job. Never raises: every outcome is recorded on the triage row."""
    try:
        with session_factory() as db:
            claimed = db.execute(
                update(TriageResult)
                .where(TriageResult.email_id == email_id, TriageResult.status == TriageStatus.queued)
                .values(status=TriageStatus.running, attempts=TriageResult.attempts + 1)
            )
            db.commit()
            if claimed.rowcount != 1:
                return  # someone else is running it, or it is already done
            try:
                email = db.get(Email, email_id)
                result = db.scalar(select(TriageResult).where(TriageResult.email_id == email_id))
                assert email is not None and result is not None
                provider = provider_factory()
                registry = ToolRegistry(
                    EmailInput(id=email.id, sender=email.sender, subject=email.subject, body=email.body),
                    lambda q, n, ex: search_emails(db, q, n, ex),
                )
                run = run_agent(
                    EmailInput(id=email.id, sender=email.sender, subject=email.subject, body=email.body),
                    provider, registry, config,
                )
                _persist(db, result, email_id, run, provider.name)
            except Exception as e:  # last-resort guard; never leak internals into the record
                log.exception("triage job crashed for email %s", email_id)
                _mark_failed(db, email_id, "internal_error", f"unexpected {type(e).__name__}")
    except Exception:  # even the failure path failed (e.g. DB down): log and give up quietly
        log.exception("triage job could not record its outcome for email %s", email_id)
