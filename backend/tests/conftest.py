import pytest
from fastapi.testclient import TestClient

from app.agent import FakeLLM
from app.config import Settings
from app.db import Base, make_engine, make_session_factory
from app.main import create_app

PASSWORD = "correct-horse-battery"


def build(provider_factory=None):
    """App + in-memory SQLite + FakeLLM. Never touches the network or a real key."""
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = make_session_factory(engine)
    settings = Settings(jwt_secret="test-secret-test-secret-test-secret-32b", agent_timeout_seconds=5)
    app = create_app(settings, sf, provider_factory or (lambda: FakeLLM()))
    return app, sf


@pytest.fixture()
def ctx():
    return build()


@pytest.fixture()
def client(ctx):
    app, _ = ctx
    return TestClient(app)


def register_and_login(client: TestClient, email: str) -> dict[str, str]:
    r = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    t = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture()
def admin(client):  # first registered user => admin
    return register_and_login(client, "admin@example.test")


@pytest.fixture()
def member(client, admin):  # registered after admin => member
    return register_and_login(client, "member@example.test")


MEETING = {
    "sender": "Ana Cruz <ana@example.test>",
    "subject": "Can we meet tomorrow?",
    "body": "Hi, could we schedule a call tomorrow to plan the launch? Please send me your availability.",
}
