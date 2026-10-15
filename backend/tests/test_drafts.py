"""Draft approval state machine: pending -> approved | rejected; terminal afterwards."""
import pytest

from tests.conftest import MEETING


@pytest.fixture()
def draft_id(client, admin):
    eid = client.post("/emails", json=MEETING, headers=admin).json()["id"]
    client.post(f"/emails/{eid}/triage", headers=admin)
    return client.get("/drafts", headers=admin).json()[0]["id"]


def test_new_drafts_start_pending_and_filter_by_status(client, admin, draft_id):
    assert len(client.get("/drafts?status=pending", headers=admin).json()) == 1
    assert client.get("/drafts?status=approved", headers=admin).json() == []
    assert client.get("/drafts?status=bogus", headers=admin).status_code == 422


def test_approve_records_decider_and_is_terminal(client, admin, member, draft_id):
    r = client.post(f"/drafts/{draft_id}/approve", headers=member)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved" and body["decided_at"]
    # terminal: cannot approve again, reject, or edit
    assert client.post(f"/drafts/{draft_id}/approve", headers=admin).status_code == 409
    assert client.post(f"/drafts/{draft_id}/reject", headers=admin).status_code == 409
    assert client.patch(f"/drafts/{draft_id}", json={"edited_body": "late edit"}, headers=admin).status_code == 409


def test_reject_is_terminal(client, admin, draft_id):
    assert client.post(f"/drafts/{draft_id}/reject", headers=admin).json()["status"] == "rejected"
    assert client.post(f"/drafts/{draft_id}/approve", headers=admin).status_code == 409


def test_edit_keeps_pending_and_final_body_uses_edit(client, admin, draft_id):
    original = client.get(f"/drafts/{draft_id}", headers=admin).json()["body"]
    r = client.patch(f"/drafts/{draft_id}", json={"edited_body": "Hi Ana, Thursday 3pm works."}, headers=admin).json()
    assert r["status"] == "pending"  # editing never approves
    assert r["body"] == original and r["edited_body"] == "Hi Ana, Thursday 3pm works."
    assert r["final_body"] == "Hi Ana, Thursday 3pm works."
    approved = client.post(f"/drafts/{draft_id}/approve", headers=admin).json()
    assert approved["final_body"] == "Hi Ana, Thursday 3pm works." and approved["status"] == "approved"


def test_edit_validation(client, admin, draft_id):
    assert client.patch(f"/drafts/{draft_id}", json={"edited_body": ""}, headers=admin).status_code == 422
    assert client.patch(f"/drafts/{draft_id}", json={"edited_body": "x" * 4001}, headers=admin).status_code == 422


def test_missing_draft_404(client, admin):
    assert client.post("/drafts/99/approve", headers=admin).status_code == 404
    assert client.post("/drafts/99/reject", headers=admin).status_code == 404
    assert client.patch("/drafts/99", json={"edited_body": "x"}, headers=admin).status_code == 404


def test_there_is_no_send_endpoint(client, admin, draft_id):
    for path in (f"/drafts/{draft_id}/send", "/send", f"/emails/{draft_id}/send"):
        assert client.post(path, headers=admin).status_code in (404, 405)
    from app.models import DraftStatus
    assert {s.value for s in DraftStatus} == {"pending", "approved", "rejected"}
