"""Endpoint behaviour through TestClient (background tasks run before the response returns)."""
from tests.conftest import MEETING


def add(client, h, **over):
    r = client.post("/emails", json={**MEETING, **over}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_add_and_list_and_get_email(client, admin):
    eid = add(client, admin)
    lst = client.get("/emails", headers=admin).json()
    assert [e["id"] for e in lst] == [eid] and lst[0]["triage_status"] is None
    d = client.get(f"/emails/{eid}", headers=admin).json()
    assert d["subject"] == MEETING["subject"] and d["triage"] is None and d["draft"] is None and d["tasks"] == []
    assert client.get("/emails/999", headers=admin).status_code == 404


def test_add_pasted_raw_text_with_headers(client, admin):
    raw = "From: Lee Park <lee@example.test>\nSubject: Quick question\n\nCan you confirm the invoice amount?"
    r = client.post("/emails", json={"raw_text": raw}, headers=admin)
    eid = r.json()["id"]
    d = client.get(f"/emails/{eid}", headers=admin).json()
    assert d["sender"].startswith("Lee Park") and d["subject"] == "Quick question" and d["body"].startswith("Can you confirm")


def test_add_pasted_text_without_headers(client, admin):
    r = client.post("/emails", json={"raw_text": "Lunch on Friday?\nLet me know if you are free."}, headers=admin)
    d = client.get(f"/emails/{r.json()['id']}", headers=admin).json()
    assert d["subject"] == "Lunch on Friday?" and d["sender"] == "unknown@pasted.invalid"


def test_add_email_validation(client, admin):
    assert client.post("/emails", json={}, headers=admin).status_code == 422
    assert client.post("/emails", json={"sender": "a@b.test", "subject": "s"}, headers=admin).status_code == 422
    both = {**MEETING, "raw_text": "x"}
    assert client.post("/emails", json=both, headers=admin).status_code == 422


def test_duplicate_message_id_conflicts(client, admin):
    add(client, admin, message_id="m-1")
    assert client.post("/emails", json={**MEETING, "message_id": "m-1"}, headers=admin).status_code == 409


def test_triage_end_to_end_produces_trace_tasks_and_pending_draft(client, admin):
    eid = add(client, admin)
    r = client.post(f"/emails/{eid}/triage", headers=admin)
    assert r.status_code == 202 and r.json()["started"] is True
    d = client.get(f"/emails/{eid}", headers=admin).json()
    t = d["triage"]
    assert t["status"] == "completed" and t["category"] == "meeting_request" and t["urgency"] == "medium"
    assert t["needs_reply"] is True and t["provider"] == "fake" and t["attempts"] == 1
    assert [s["tool"] for s in t["trace"]] == [
        "search_past_emails", "classify_email", "extract_tasks", "draft_reply", "final"]
    assert all({"step", "tool", "args", "result", "error", "latency_ms"} <= s.keys() for s in t["trace"])
    assert d["tasks"] and d["draft"]["status"] == "pending" and d["draft"]["body"].startswith("Hi Ana")
    # list view reflects it
    row = client.get("/emails", headers=admin).json()[0]
    assert (row["triage_status"], row["category"], row["draft_status"]) == ("completed", "meeting_request", "pending")


def test_triage_is_idempotent_no_duplicate_drafts(client, admin):
    eid = add(client, admin)
    first = client.post(f"/emails/{eid}/triage", headers=admin)
    second = client.post(f"/emails/{eid}/triage", headers=admin)
    assert first.status_code == 202 and second.status_code == 200
    assert second.json() == {"email_id": eid, "status": "completed", "started": False}
    assert len(client.get("/drafts", headers=admin).json()) == 1
    assert client.get(f"/emails/{eid}", headers=admin).json()["triage"]["attempts"] == 1  # no second run


def test_triage_unknown_email_404(client, admin):
    assert client.post("/emails/404/triage", headers=admin).status_code == 404


def test_spam_gets_no_draft(client, admin):
    eid = add(client, admin, sender="x@spam.example.test", subject="You have won!",
              body="Congratulations, click here to claim your free gift. Act now!")
    client.post(f"/emails/{eid}/triage", headers=admin)
    d = client.get(f"/emails/{eid}", headers=admin).json()
    assert d["triage"]["category"] == "spam" and d["triage"]["needs_reply"] is False and d["draft"] is None


def test_search_past_emails_tool_sees_earlier_mail(client, admin):
    add(client, admin, subject="Launch plan v1", body="Draft of the launch plan attached.", message_id="old")
    eid = add(client, admin, subject="Launch plan follow-up", body="Can we talk about the launch plan? Let me know.")
    client.post(f"/emails/{eid}/triage", headers=admin)
    trace = client.get(f"/emails/{eid}", headers=admin).json()["triage"]["trace"]
    matches = trace[0]["result"]["matches"]
    assert [m["subject"] for m in matches] == ["Launch plan v1"]  # excludes the email itself
