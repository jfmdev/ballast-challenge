import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "test")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
import ratelimit
import worker
from database import Base, get_db


class FakePipeline:
    def __init__(self, store):
        self.store = store
        self.key = None

    def incr(self, key):
        self.key = key
        self.store[key] = self.store.get(key, 0) + 1

    def expire(self, key, seconds, nx=False):
        pass

    def execute(self):
        return [self.store[self.key], True]


class FakeRedis:
    def __init__(self):
        self.store = {}

    def pipeline(self):
        return FakePipeline(self.store)


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(ratelimit, "redis_client", client)
    return client


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(worker, "SessionLocal", factory)

    def override_get_db():
        with factory() as session:
            yield session

    main.app.dependency_overrides[get_db] = override_get_db
    yield factory
    main.app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(session_factory):
    with TestClient(main.app) as test_client:
        yield test_client


def _login(client, email="john@doe.com", password="abc123"):
    return client.post("/login", data={"username": email, "password": password})


@pytest.fixture
def auth_headers(client):
    token = _login(client).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
