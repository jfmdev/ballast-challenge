from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from argon2 import PasswordHasher
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import Base, SessionLocal, engine, get_db
from models import Task, User
from schemas import TaskCreate, TaskPage, TaskRead, TaskUpdate, Token
from ratelimit import login_rate_limit, rate_limit
from security import create_access_token, get_current_user, verify_password

password_hasher = PasswordHasher()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)

    # Create the initial user if it doesn't exist.
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.email == "john@doe.com"))
        if user is None:
            session.add(
                User(
                    name="John Doe",
                    email="john@doe.com",
                    password=password_hasher.hash("abc123"),
                )
            )
            session.commit()
    yield


app = FastAPI(
    title="Task Manager API",
    description="REST API to manage personal tasks. Authenticate via `/login` and use the bearer token.",
    version="1.0.0",
    lifespan=lifespan,
    dependencies=[Depends(rate_limit)],
    openapi_tags=[
        {"name": "system", "description": "Service status."},
        {"name": "auth", "description": "Authentication."},
        {"name": "tasks", "description": "CRUD operations on the authenticated user's tasks."},
    ],
)

UNAUTHORIZED = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing, invalid or expired token"},
    status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Rate limit exceeded"},
}
NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "Task not found"}}


@app.get("/health", tags=["system"], summary="Health check")
def health():
    return {"status": "ok"}


@app.post(
    "/login",
    response_model=Token,
    tags=["auth"],
    summary="Obtain an access token",
    dependencies=[Depends(login_rate_limit)],
    description="Form login where `username` is the user's email. Returns a JWT bearer token.",
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Invalid email or password"}},
)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
) -> Token:
    user = db.scalar(select(User).where(User.email == form_data.username))
    if user is None or not verify_password(form_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user.id))


def get_owned_task(db: Session, task_id: int, user_id: int) -> Task:
    task = db.scalar(
        select(Task).where(Task.id == task_id, Task.user_id == user_id)
    )
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    return task


@app.post(
    "/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    tags=["tasks"],
    summary="Create a task",
    responses=UNAUTHORIZED,
)
def create_task(
    task_data: TaskCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    task = Task(user_id=current_user.id, **task_data.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@app.get(
    "/tasks",
    response_model=TaskPage,
    tags=["tasks"],
    summary="List tasks",
    description="Paginated list of the user's tasks ordered by due date, optionally filtered by completion.",
    responses=UNAUTHORIZED,
)
def list_tasks(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    completed: bool | None = None,
) -> TaskPage:
    filters = [Task.user_id == current_user.id]
    if completed is not None:
        filters.append(Task.completed == completed)

    total = db.scalar(select(func.count(Task.id)).where(*filters)) or 0
    tasks = db.scalars(
        select(Task)
        .where(*filters)
        .order_by(Task.due_date.asc(), Task.id.asc())
        .offset(skip)
        .limit(limit)
    ).all()
    return TaskPage(items=tasks, total=total, skip=skip, limit=limit)


@app.get(
    "/tasks/{task_id}",
    response_model=TaskRead,
    tags=["tasks"],
    summary="Get a task",
    responses={**UNAUTHORIZED, **NOT_FOUND},
)
def read_task(
    task_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    return get_owned_task(db, task_id, current_user.id)


@app.patch(
    "/tasks/{task_id}",
    response_model=TaskRead,
    tags=["tasks"],
    summary="Update a task",
    description="Partially update a task. At least one non-null field is required.",
    responses={
        **UNAUTHORIZED,
        **NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "Invalid or empty update"},
    },
)
def update_task(
    task_id: int,
    task_data: TaskUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    updates = task_data.model_dump(exclude_unset=True)
    if not updates or any(value is None for value in updates.values()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one non-null field to update",
        )

    task = get_owned_task(db, task_id, current_user.id)
    for field, value in updates.items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


@app.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["tasks"],
    summary="Delete a task",
    responses={**UNAUTHORIZED, **NOT_FOUND},
)
def delete_task(
    task_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    task = get_owned_task(db, task_id, current_user.id)
    db.delete(task)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "public", html=True),
    name="public",
)
