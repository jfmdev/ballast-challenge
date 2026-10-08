import logging
import os
import time

import redis
from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    password=os.getenv("REDIS_PASSWORD") or None,
    socket_timeout=1,
    socket_connect_timeout=1,
)

WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
GLOBAL_LIMIT = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
LOGIN_LIMIT = int(os.getenv("RATE_LIMIT_LOGIN_REQUESTS", "5"))


def _enforce(scope: str, client: str, limit: int) -> None:
    window = int(time.time()) // WINDOW_SECONDS
    key = f"ratelimit:{scope}:{client}:{window}"
    try:
        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, WINDOW_SECONDS, nx=True)
        count = pipe.execute()[0]
    except redis.RedisError:
        # Fail open so a Redis outage doesn't take the API down.
        logger.warning("Rate limiter unavailable", exc_info=True)
        return

    if count > limit:
        retry_after = WINDOW_SECONDS - int(time.time()) % WINDOW_SECONDS
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={"Retry-After": str(retry_after)},
        )


def _client_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request) -> None:
    _enforce("global", _client_id(request), GLOBAL_LIMIT)


def login_rate_limit(request: Request) -> None:
    _enforce("login", _client_id(request), LOGIN_LIMIT)
