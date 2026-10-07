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

## License

This application is free software; you can redistribute it and/or modify it under the terms of the Mozilla Public License v2.0. You should have received a copy of the MPL 2.0 along with this library, otherwise you can obtain one at http://mozilla.org/MPL/2.0/.