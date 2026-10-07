from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    due_date: datetime
    completed: bool = False


class TaskUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    due_date: datetime | None = None
    completed: bool | None = None


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