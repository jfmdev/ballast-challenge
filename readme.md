# Ballast Lane Applications - Technical Exercise - Python

> A RESTful API for a simple task management system

## Requirements

To run this application, you'll need the following:

* A running Redis instance.
* A running Postgres instance.

After obtaining these, create a `.env` file inside the `/app` directory with the following content:

```env
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=redis_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres_user
POSTGRES_PASSWORD=postgres_password
POSTGRES_DB=ballast
JWT_SECRET_KEY=replace-with-a-long-random-secret
```

Make sure the both Redis and Postgres instances are accessible from your environment.

> Note that you don’t need to set the variables manually if you're using Docker Compose (on this case the environment is configured automatically).

## Running locally

You can run the project using a Python virtual environment or Docker.

### Using a Virtual Environment

```bash
# Create a virtual environment (only once)
python3 -m venv ./my-env

# Activate the virtual environment
source ./my-env/bin/activate

# Install dependencies (only once)
pip install -r ./app/requirements.txt

# Navigate to the app directory
cd app

# Run the FastAPI application
uvicorn main:app --reload
```

The app will be available at http://localhost:8000

## API

### Login

`POST /login` accepts form-encoded `username` (the user's email) and `password`. It returns an access token; send it as `Authorization: Bearer <token>` to access task endpoints. The seeded development account is `john@doe.com` with password `abc123`.

### Tasks

All task routes require a bearer token and operate only on the authenticated user's tasks.

* `POST /tasks` creates a task with `name` and `due_date`; `completed` defaults to `false`.
* `GET /tasks` lists tasks, sorted by due date ascending. Use `skip` and `limit` for pagination (`limit` is capped at 100), and optionally set `completed=true` or `completed=false` to filter.
* `GET /tasks/{task_id}` retrieves one task.
* `PATCH /tasks/{task_id}` updates any of `name`, `due_date`, or `completed`.
* `DELETE /tasks/{task_id}` deletes a task.

JWT access tokens expire after 30 minutes. Set `JWT_SECRET_KEY` to a strong, private value outside local development.

### Using Docker

You can run both the FastAPI application, Redis and Postgres using Docker Compose (recommended), or you can manage containers manually.

#### Docker Compose

```bash
docker compose up
```

This will automatically build and start the FastAPI app, Redis, and PostgreSQL services.

#### Manual Docker setup

##### Start Redis with Docker

```bash
# Run Redis container (first time)
docker run -d --name ballast-app-redis -p 6379:6379 redis:7-alpine \
	redis-server --requirepass redis_password

# Start Redis if it's already created
docker start ballast-app-redis
```

Redis will be available at: `redis://:redis_password@localhost:6379`

> To stop the Redis container when you're done: `docker stop ballast-app-redis`

##### Start Postgres with Docker

```bash
# Run the Postgres container (first time)
docker run -d --name ballast-app-postgres \
	-e POSTGRES_USER=postgres_user \
	-e POSTGRES_PASSWORD=postgres_password \
	-e POSTGRES_DB=ballast \
	-p 5432:5432 \
	-v ballast-postgres-data:/var/lib/postgresql/data \
	postgres:16-alpine

# Start Postgres if the container already exists
docker start ballast-app-postgres
```

Postgres will be available at `localhost:5432`. Use the credentials above when configuring the application.

> To stop the Postgres container when you're done: `docker stop ballast-app-postgres`

##### Main application

```bash
# Build the Docker image (only once)
docker build -t ballast-app-main ./app

# Run the Docker container
docker run -p 8000:8000 ballast-app-main
```

The app will be accessible at http://localhost:8000

## Design and implementation

The project was built incrementally with GitHub Copilot, one reviewable commit per step (see `git log`):

1. **Bare-bones FastAPI backend** and a **Docker Compose** file with the app, Redis and Postgres, so the whole stack ran from day one.
2. **Schema and endpoint drafts:** `users` and `tasks` tables (SQLAlchemy 2.0), JWT login and task CRUD.
3. **Frontend:** a static page in `app/public`, served by FastAPI and consuming the same API.
4. **Swagger metadata:** tags, summaries, documented error responses and field descriptions.
5. **Rate limiting** with Redis.
6. **Background job** with Celery + Redis.
7. **Unit tests** with pytest.

### Architecture

| File | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI app, routes, startup (table creation and demo user seeding) |
| `app/schemas.py` | Pydantic request/response models and validation |
| `app/models.py` | SQLAlchemy models (`User`, `Task`) |
| `app/database.py` | Engine, session factory and the `get_db` dependency |
| `app/security.py` | Argon2 password verification, JWT creation, `get_current_user` |
| `app/ratelimit.py` | Redis rate-limit dependencies |
| `app/worker.py` | Celery app, Beat schedule and background tasks |

Routes depend on abstractions injected through FastAPI's dependency system (DB session, current user, rate limiter), which keeps them thin and lets tests swap infrastructure. This is a deliberately small codebase, so it is layered by module rather than a full Clean Architecture split (no separate service/repository layers).

### Key decisions

* **FastAPI + Postgres:** type-driven validation, automatic OpenAPI docs, and a production-grade database. Tests use in-memory SQLite.
* **Authentication:** OAuth2 password flow, with the email as `username` so Swagger's *Authorize* button works. JWTs are HS256 and expire after 30 minutes; passwords are hashed with Argon2. A malformed stored hash is treated as a failed login rather than a server error.
* **Ownership:** every task query filters by the authenticated user, and another user's task returns `404` instead of `403` so its existence is not leaked.
* **Partial updates:** `PATCH` uses `exclude_unset`, and rejects empty bodies or explicit `null` values (the columns are non-nullable).
* **Pagination:** `skip`/`limit` (`limit` capped at 100) with a response envelope `{items, total, skip, limit}`, ordered by `due_date, id` so pages are stable.
* **Rate limiting:** fixed-window counter in Redis (`INCR` + `EXPIRE NX` in one pipeline, so it is atomic), keyed by client IP. Global limit of 100 requests/min and a stricter 5/min on `/login` against brute force. It returns `429` with `Retry-After`, and fails open (with a warning) if Redis is down. Limits are configurable with `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_LOGIN_REQUESTS` and `RATE_LIMIT_WINDOW_SECONDS`. Behind a reverse proxy, run uvicorn with `--proxy-headers`.
* **Background processing:** the `worker` Compose service runs Celery with Beat. `tasks.notify_overdue_tasks` runs every 60 seconds, finds tasks with `due_date < now` and `completed = false`, and logs a warning for each one (`docker compose logs -f worker`). Due dates are assumed to be UTC.
* **Secrets:** read from the environment; `JWT_SECRET_KEY` has a development-only default in Compose only.

### Testing

Tests live in `app/tests` and cover login, authentication failures, task CRUD, validation, pagination and filtering, ownership isolation, rate limiting (including Redis outage) and the Celery task. The database is replaced with in-memory SQLite and Redis with a fake, so no services are needed.

```bash
cd app
pip install -r requirements-dev.txt
python -m pytest   # fails if coverage drops below 80%
```

### Known limitations

* Tasks can only be filtered by status (`completed`); filtering by due date is not implemented yet.
* Tasks belong to their creator; assigning a task to a different user is not implemented.
* The overdue job logs repeatedly for the same task on every run and does not track what was already notified.
* The frontend is a single static page rather than a React/Vue application.
* There is no migration tool (tables are created at startup) and no `pyproject.toml` or pre-commit configuration.

### Use of GenAI

Copilot generated each step from a short, focused prompt (for example "Implement a Rate Limit protection, to prevent abuses of the API, using Redis"). Its output was checked by:

* **Reading and editing:** reviewing every diff and keeping changes small. For example, the first rate-limit and Swagger drafts were adjusted to match existing helpers and conventions.
* **Tests as validation:** the generated tests found a real bug. `argon2` raises `InvalidHashError`, which is not a `VerificationError`, so a malformed hash would have caused a `500` on login. It was fixed in `security.py`.
* **Edge cases:** ownership, empty or null `PATCH` bodies, token expiry, unknown users, pagination bounds and Redis outages are all covered by tests.
* **Idiomatic quality:** SQLAlchemy 2.0 `select()` style, `Annotated` dependencies, Pydantic v2 models, and an atomic Redis pipeline instead of separate get/set calls.

## License

This application is free software; you can redistribute it and/or modify it under the terms of the Mozilla Public License v2.0. You should have received a copy of the MPL 2.0 along with this library, otherwise you can obtain one at http://mozilla.org/MPL/2.0/.