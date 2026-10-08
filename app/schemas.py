from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50, description="Task name", examples=["Buy milk"])
    due_date: datetime = Field(description="Due date and time", examples=["2026-12-31T18:00:00"])
    completed: bool = Field(default=False, description="Whether the task is done")


class TaskUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50, description="New task name")
    due_date: datetime | None = Field(default=None, description="New due date and time")
    completed: bool | None = Field(default=None, description="New completion status")


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    user_id: int
    completed: bool
    due_date: datetime


class TaskPage(BaseModel):
    items: list[TaskRead]
    total: int
    skip: int
    limit: int