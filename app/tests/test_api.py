from datetime import datetime, timedelta, timezone

import jwt
import pytest
import redis
from argon2 import PasswordHasher

import ratelimit
import security
import worker
from models import Task, User
from tests.conftest import _login

DUE = "2030-01-01T10:00:00"


def create_task(client, headers, **overrides):
    payload = {"name": "Task", "due_date": DUE, **overrides}
    return client.post("/tasks", json=payload, headers=headers)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_static_index_served(client):
    assert client.get("/").status_code == 200


def test_initial_user_not_duplicated(client, session_factory):
    with client:
        pass
    with session_factory() as session:
        assert session.query(User).count() == 1


class TestLogin:
    def test_success(self, client):
        response = _login(client)
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]

    def test_wrong_password(self, client):
        response = _login(client, password="wrong")
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_unknown_user(self, client):
        assert _login(client, email="nobody@x.com").status_code == 401

    def test_rate_limited(self, client, monkeypatch):
        monkeypatch.setattr(ratelimit, "LOGIN_LIMIT", 2)
        assert _login(client, password="x").status_code == 401
        assert _login(client, password="x").status_code == 401
        response = _login(client, password="x")
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) > 0


class TestAuth:
    def test_missing_token(self, client):
        assert client.get("/tasks").status_code == 401

    def test_invalid_token(self, client):
        response = client.get("/tasks", headers={"Authorization": "Bearer garbage"})
        assert response.status_code == 401

    def test_expired_token(self, client):
        token = jwt.encode(
            {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
            security.JWT_SECRET_KEY,
            algorithm=security.JWT_ALGORITHM,
        )
        response = client.get("/tasks", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_token_for_missing_user(self, client):
        token = security.create_access_token(9999)
        response = client.get("/tasks", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_verify_password_invalid_hash(self):
        assert security.verify_password("abc", "not-a-hash") is False


class TestCreateTask:
    def test_success(self, client, auth_headers):
        response = create_task(client, auth_headers, name="Buy milk")
        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Buy milk"
        assert body["completed"] is False
        assert body["id"] > 0

    @pytest.mark.parametrize(
        "payload",
        [
            {"due_date": DUE},
            {"name": "", "due_date": DUE},
            {"name": "x" * 51, "due_date": DUE},
            {"name": "ok", "due_date": "not-a-date"},
        ],
    )
    def test_validation(self, client, auth_headers, payload):
        response = client.post("/tasks", json=payload, headers=auth_headers)
        assert response.status_code == 422

    def test_requires_auth(self, client):
        response = client.post("/tasks", json={"name": "a", "due_date": DUE})
        assert response.status_code == 401


class TestListTasks:
    def test_empty(self, client, auth_headers):
        body = client.get("/tasks", headers=auth_headers).json()
        assert body == {"items": [], "total": 0, "skip": 0, "limit": 20}

    def test_ordering_pagination_and_filter(self, client, auth_headers):
        create_task(client, auth_headers, name="late", due_date="2031-01-01T00:00:00")
        create_task(client, auth_headers, name="early", due_date="2029-01-01T00:00:00")
        done = create_task(
            client, auth_headers, name="done", due_date="2030-01-01T00:00:00"
        ).json()
        client.patch(f"/tasks/{done['id']}", json={"completed": True}, headers=auth_headers)

        body = client.get("/tasks", headers=auth_headers).json()
        assert [t["name"] for t in body["items"]] == ["early", "done", "late"]
        assert body["total"] == 3

        page = client.get("/tasks?skip=1&limit=1", headers=auth_headers).json()
        assert [t["name"] for t in page["items"]] == ["done"]
        assert page["total"] == 3

        completed = client.get("/tasks?completed=true", headers=auth_headers).json()
        assert [t["name"] for t in completed["items"]] == ["done"]
        pending = client.get("/tasks?completed=false", headers=auth_headers).json()
        assert pending["total"] == 2

    @pytest.mark.parametrize("query", ["skip=-1", "limit=0", "limit=101"])
    def test_invalid_pagination(self, client, auth_headers, query):
        assert client.get(f"/tasks?{query}", headers=auth_headers).status_code == 422

    def test_only_own_tasks(self, client, auth_headers, session_factory):
        with session_factory() as session:
            other = User(
                name="Other",
                email="other@x.com",
                password=PasswordHasher().hash("pw"),
            )
            session.add(other)
            session.commit()
            session.add(
                Task(
                    name="secret",
                    user_id=other.id,
                    completed=False,
                    due_date=datetime(2030, 1, 1),
                )
            )
            session.commit()
        body = client.get("/tasks", headers=auth_headers).json()
        assert body["total"] == 0


class TestReadTask:
    def test_success(self, client, auth_headers):
        task_id = create_task(client, auth_headers).json()["id"]
        response = client.get(f"/tasks/{task_id}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["id"] == task_id

    def test_not_found(self, client, auth_headers):
        assert client.get("/tasks/999", headers=auth_headers).status_code == 404

    def test_other_users_task_is_404(self, client, auth_headers, session_factory):
        with session_factory() as session:
            other = User(name="O", email="o@x.com", password="x")
            session.add(other)
            session.commit()
            task = Task(
                name="t", user_id=other.id, completed=False, due_date=datetime(2030, 1, 1)
            )
            session.add(task)
            session.commit()
            task_id = task.id
        assert client.get(f"/tasks/{task_id}", headers=auth_headers).status_code == 404


class TestUpdateTask:
    def test_success(self, client, auth_headers):
        task_id = create_task(client, auth_headers).json()["id"]
        response = client.patch(
            f"/tasks/{task_id}",
            json={"name": "Renamed", "completed": True},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Renamed"
        assert response.json()["completed"] is True

    @pytest.mark.parametrize("payload", [{}, {"name": None}])
    def test_empty_or_null_update(self, client, auth_headers, payload):
        task_id = create_task(client, auth_headers).json()["id"]
        response = client.patch(f"/tasks/{task_id}", json=payload, headers=auth_headers)
        assert response.status_code == 422

    def test_not_found(self, client, auth_headers):
        response = client.patch("/tasks/999", json={"name": "x"}, headers=auth_headers)
        assert response.status_code == 404


class TestDeleteTask:
    def test_success(self, client, auth_headers):
        task_id = create_task(client, auth_headers).json()["id"]
        response = client.delete(f"/tasks/{task_id}", headers=auth_headers)
        assert response.status_code == 204
        assert client.get(f"/tasks/{task_id}", headers=auth_headers).status_code == 404

    def test_not_found(self, client, auth_headers):
        assert client.delete("/tasks/999", headers=auth_headers).status_code == 404


class TestRateLimit:
    def test_global_limit(self, client, monkeypatch):
        monkeypatch.setattr(ratelimit, "GLOBAL_LIMIT", 2)
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 429

    def test_fails_open_when_redis_down(self, client, monkeypatch):
        class BrokenRedis:
            def pipeline(self):
                raise redis.RedisError("down")

        monkeypatch.setattr(ratelimit, "redis_client", BrokenRedis())
        assert client.get("/health").status_code == 200


class TestOverdueWorker:
    def test_logs_only_overdue_incomplete(self, client, session_factory, caplog):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with session_factory() as session:
            user_id = session.query(User).first().id
            session.add_all(
                [
                    Task(name="overdue", user_id=user_id, completed=False,
                         due_date=now - timedelta(hours=1)),
                    Task(name="done", user_id=user_id, completed=True,
                         due_date=now - timedelta(hours=1)),
                    Task(name="future", user_id=user_id, completed=False,
                         due_date=now + timedelta(hours=1)),
                ]
            )
            session.commit()

        with caplog.at_level("WARNING", logger="worker"):
            count = worker.notify_overdue_tasks()

        assert count == 1
        assert "Task overdue" in caplog.text
        assert "overdue" in caplog.text and "'done'" not in caplog.text
