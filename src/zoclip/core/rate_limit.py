from fastapi import Request
from redis.exceptions import RedisError

from zoclip.core.errors import ApiError
from zoclip.core.security import digest

SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""


def rate_limit(request: Request, scope: str, account: str | None = None) -> None:
    settings = request.app.state.settings
    ip = request.client.host if request.client else "unknown"
    keys = [f"auth:{scope}:ip:{digest(ip)}"]
    if account:
        keys.append(f"auth:{scope}:account:{digest(account)}")
    try:
        for key in keys:
            count = request.app.state.redis.eval(SCRIPT, 1, key, settings.auth_rate_window_seconds)
            if int(count) > settings.auth_rate_limit:
                raise ApiError(429, "rate_limited", "Too many attempts; retry later.")
    except RedisError as exc:
        raise ApiError(
            503, "rate_limit_unavailable", "Authentication temporarily unavailable."
        ) from exc
