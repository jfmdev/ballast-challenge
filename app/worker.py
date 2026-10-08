import logging
import os
from datetime import datetime, timezone

from celery import Celery
from sqlalchemy import select

from database import SessionLocal
from models import Task

logger = logging.getLogger(__name__)

_password = os.getenv("REDIS_PASSWORD", "")
REDIS_URL = "redis://{auth}{host}:{port}/0".format(
    auth=f":{_password}@" if _password else "",
    host=os.getenv("REDIS_HOST", "localhost"),
    port=os.getenv("REDIS_PORT", "6379"),
)

celery_app = Celery("ballast", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    "notify-overdue-tasks": {
        "task": "tasks.notify_overdue_tasks",
        "schedule": 60.0,
    },
}


@celery_app.task(name="tasks.notify_overdue_tasks")
def notify_overdue_tasks() -> int:
    # Task.due_date is a naive column, assumed UTC.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as session:
        overdue = session.scalars(
            select(Task).where(Task.due_date < now, Task.completed.is_(False))
        ).all()
        for task in overdue:
            logger.warning(
                "Task overdue: id=%s name=%r user_id=%s due_date=%s",
                task.id,
                task.name,
                task.user_id,
                task.due_date.isoformat(),
            )
    return len(overdue)
