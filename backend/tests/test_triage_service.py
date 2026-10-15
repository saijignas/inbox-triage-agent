"""Failure handling and idempotency at the service level."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.agent import FakeLLM
from app.agent.errors import LLMTimeout
from app.agent.schemas import LLMResponse, ToolCall
from app.models import Draft, Email, Task, TriageResult, TriageStatus
from app.services.triage import claim_triage, run_triage_job
from tests.conftest import MEETING, build, register_and_login


def seed_email(sf):
    with sf() as db:
        e = Email(sender=MEETING["sender"], subject=MEETING["subject"], body=MEETING["body"])
        db.add(e)
        db.commit()
        return e.id


def row(sf, email_id):
    with sf() as db:
        return db.scalar(select(TriageResult).where(TriageResult.email_id == email_id))


def test_claim_is_compare_and_set(ctx):
    _, sf = ctx
    eid = seed_email(sf)
    with sf() as db:
        _, first = claim_triage(db, eid)
        _, second = claim_triage(db, eid)
    assert (first, second) == (True, False)


def test_running_job_twice_creates_one_draft_and_one_run(ctx):
    _, sf = ctx
    eid = seed_email(sf)
    with sf() as db:
        claim_triage(db, eid)
    for _ in range(2):
        run_triage_job(sf, lambda: FakeLLM(), eid)
    with sf() as db:
        assert db.scalar(select(func.count()).select_from(Draft)) == 1
        assert db.scalar(select(func.count()).select_from(Task)) >= 1
    assert row(sf, eid).attempts == 1 and row(sf, eid).status == TriageStatus.completed


def test_completed_email_is_not_claimable_again(ctx):
    _, sf = ctx
    eid = seed_email(sf)
    with sf() as db:
        claim_triage(db, eid)
    run_triage_job(sf, lambda: FakeLLM(), eid)
    with sf() as db:
        _, claimed = claim_triage(db, eid)
    assert claimed is False


def test_db_unique_constraint_backstops_duplicate_drafts(ctx):
    from sqlalchemy.exc import IntegrityError
    _, sf = ctx
    eid = seed_email(sf)
    with sf() as db:
        db.add(Draft(email_id=eid, body="one", tone="formal"))
        db.commit()
        db.add(Draft(email_id=eid, body="two", tone="formal"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_llm_timeout_is_recorded_as_failure_not_a_crash_and_retry_succeeds(monkeypatch):
    # 1st request: provider times out on every attempt -> failed. 2nd request: healthy provider.
    flaky = {"on": True}

    def factory():
        return FakeLLM([LLMTimeout("t")] * 10) if flaky["on"] else FakeLLM()

    app, sf = build(factory)
    c = TestClient(app)
    h = register_and_login(c, "a@example.test")
    eid = c.post("/emails", json=MEETING, headers=h).json()["id"]

    monkeypatch.setattr("app.agent.loop.time.sleep", lambda s: None)  # no real backoff waiting
    r = c.post(f"/emails/{eid}/triage", headers=h)
    assert r.status_code == 202
    t = c.get(f"/emails/{eid}", headers=h).json()
    assert t["triage"]["status"] == "failed" and t["triage"]["error_code"] == "llm_timeout"
    assert t["draft"] is None and t["tasks"] == []
    assert any(s["tool"] == "llm" and "llm_timeout" in s["error"] for s in t["triage"]["trace"])

    flaky["on"] = False
    retry = c.post(f"/emails/{eid}/triage", headers=h)
    assert retry.status_code == 202 and retry.json()["started"] is True
    t = c.get(f"/emails/{eid}", headers=h).json()
    assert t["triage"]["status"] == "completed" and t["triage"]["attempts"] == 2
    assert t["triage"]["error_code"] is None and t["draft"]["status"] == "pending"


def test_invalid_tool_args_twice_records_failure_and_leaves_no_draft():
    bad = LLMResponse(tool_call=ToolCall(name="classify_email", arguments={"category": "zzz", "urgency": "low"}))
    app, sf = build(lambda: FakeLLM([bad, bad]))
    c = TestClient(app)
    h = register_and_login(c, "a@example.test")
    eid = c.post("/emails", json=MEETING, headers=h).json()["id"]
    c.post(f"/emails/{eid}/triage", headers=h)
    t = c.get(f"/emails/{eid}", headers=h).json()
    assert t["triage"]["status"] == "failed" and t["triage"]["error_code"] == "invalid_tool_arguments"
    assert t["draft"] is None and c.get("/drafts", headers=h).json() == []


def test_provider_factory_crash_is_recorded_as_internal_error():
    def boom():
        raise RuntimeError("provider construction exploded")

    app, sf = build(boom)
    c = TestClient(app)
    h = register_and_login(c, "a@example.test")
    eid = c.post("/emails", json=MEETING, headers=h).json()["id"]
    assert c.post(f"/emails/{eid}/triage", headers=h).status_code == 202  # request itself never errors
    t = c.get(f"/emails/{eid}", headers=h).json()["triage"]
    assert t["status"] == "failed" and t["error_code"] == "internal_error"
    assert "exploded" not in (t["error_message"] or "")  # internals not leaked


def test_agent_failure_does_not_persist_partial_classification(monkeypatch):
    script = [
        LLMResponse(tool_call=ToolCall(name="classify_email", arguments={"category": "billing", "urgency": "low"})),
        LLMTimeout("t"), LLMTimeout("t"), LLMTimeout("t"),
    ]
    app, sf = build(lambda: FakeLLM(script))
    c = TestClient(app)
    h = register_and_login(c, "a@example.test")
    eid = c.post("/emails", json=MEETING, headers=h).json()["id"]
    monkeypatch.setattr("app.agent.loop.time.sleep", lambda s: None)
    c.post(f"/emails/{eid}/triage", headers=h)
    t = c.get(f"/emails/{eid}", headers=h).json()["triage"]
    assert t["status"] == "failed" and t["category"] is None
