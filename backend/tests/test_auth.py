import time

import jwt
from fastapi.testclient import TestClient

from app.auth import hash_password, verify_password
from tests.conftest import PASSWORD, register_and_login


def test_password_hash_roundtrip_and_salting():
    h1, h2 = hash_password("secret-pass-1"), hash_password("secret-pass-1")
    assert h1 != h2 and "secret-pass-1" not in h1
    assert verify_password("secret-pass-1", h1)
    assert not verify_password("wrong", h1)
    assert not verify_password("x", "garbage")


def test_register_login_me(client):
    h = register_and_login(client, "a@example.test")
    me = client.get("/auth/me", headers=h).json()
    assert me["email"] == "a@example.test" and me["role"] == "admin"
    assert "password" not in str(me)


def test_first_user_admin_then_members(client):
    register_and_login(client, "a@example.test")
    h2 = register_and_login(client, "b@example.test")
    assert client.get("/auth/me", headers=h2).json()["role"] == "member"


def test_duplicate_and_invalid_registration(client):
    register_and_login(client, "a@example.test")
    assert client.post("/auth/register", json={"email": "A@example.test", "password": PASSWORD}).status_code == 409
    assert client.post("/auth/register", json={"email": "not-an-email", "password": PASSWORD}).status_code == 422
    assert client.post("/auth/register", json={"email": "c@example.test", "password": "short"}).status_code == 422


def test_login_failures_are_indistinguishable(client):
    register_and_login(client, "a@example.test")
    wrong_pw = client.post("/auth/login", json={"email": "a@example.test", "password": "nope-nope-nope"})
    no_user = client.post("/auth/login", json={"email": "ghost@example.test", "password": "nope-nope-nope"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


def test_protected_routes_require_a_valid_token(client):
    for method, path in [("get", "/emails"), ("get", "/drafts"), ("post", "/emails/1/triage"), ("post", "/drafts/1/approve")]:
        assert getattr(client, method)(path).status_code == 401
    assert client.get("/emails", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_expired_and_wrong_secret_tokens_rejected(client):
    register_and_login(client, "a@example.test")
    expired = jwt.encode({"sub": "1", "exp": int(time.time()) - 10}, "test-secret-test-secret-test-secret-32b", algorithm="HS256")
    forged = jwt.encode({"sub": "1", "exp": int(time.time()) + 600}, "other-secret-other-secret-other-secret-1", algorithm="HS256")
    for tok in (expired, forged):
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_role_check_seed_is_admin_only(client, admin, member):
    assert client.post("/emails/seed", headers=member).status_code == 403
    r = client.post("/emails/seed", headers=admin)
    assert r.status_code == 201 and r.json() == {"added": 8, "total": 8}
    assert client.post("/emails/seed", headers=admin).json()["added"] == 0  # idempotent


def test_health_is_public(client):
    assert TestClient(client.app).get("/health").json()["status"] == "ok"
