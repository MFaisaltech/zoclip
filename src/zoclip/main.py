import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from zoclip.ai.routes import router as ai_router
from zoclip.auth.email import build_email
from zoclip.auth.google import GoogleOIDC
from zoclip.auth.google import router as google_router
from zoclip.auth.routes import router
from zoclip.core.config import Settings
from zoclip.core.db import build_engine
from zoclip.core.errors import ApiError, Problem, problem_response
from zoclip.credits.routes import router as credits_router
from zoclip.media.routes import router as media_router
from zoclip.rendering.routes import router as rendering_router

logger = logging.getLogger("zoclip.requests")


class Health(BaseModel):
    status: str


class RequestBoundary:
    def __init__(self, app: ASGIApp, production: bool):
        self.app, self.production = app, production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        status = 500

        async def safe_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).extend(
                    [
                        (b"x-request-id", request_id.encode()),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"cache-control", b"no-store"),
                        (b"content-security-policy", b"frame-ancestors 'none'"),
                    ]
                )
                if self.production:
                    message["headers"].append((b"strict-transport-security", b"max-age=31536000"))
            await send(message)

        try:
            # Only the exact authenticated chunk endpoint streams a larger body.
            # Its handler enforces its admitted part length, checksum and deadline.
            messages: list[Message] = []
            size = 0
            chunk_route = scope["method"] == "PUT" and re.fullmatch(
                r"/api/v1/uploads/[a-fA-F0-9-]{36}/parts/[0-9]+", scope["path"]
            )
            if scope["method"] in {"POST", "PUT", "PATCH"} and not chunk_route:
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    size += len(message.get("body", b""))
                    if size > 16384:
                        error = await problem_response(
                            Request(scope),
                            ApiError(413, "request_too_large", "Request body exceeds 16 KiB."),
                        )
                        await error(scope, receive, safe_send)
                        return
                    messages.append(message)
                    if not message.get("more_body", False):
                        break

            async def buffered_receive() -> Message:
                if messages:
                    return messages.pop(0)
                return await receive()

            await self.app(scope, buffered_receive, safe_send)
        finally:
            # No query strings, bodies, cookies, headers, email or exception text.
            logger.info(
                json.dumps({"request_id": request_id, "method": scope["method"], "status": status})
            )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()  # type: ignore[call-arg]
    engine = build_engine(settings.database_url.get_secret_value())
    redis = Redis.from_url(
        settings.redis_url.get_secret_value(), socket_timeout=3, socket_connect_timeout=3
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        yield
        redis.close()
        engine.dispose()

    error_responses: dict[int | str, dict[str, Any]] = {
        status: {
            "model": Problem,
            "description": "Structured error",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        }
        for status in (400, 401, 403, 404, 408, 409, 413, 422, 429, 503, 507)
    }
    app = FastAPI(
        title="ZoClip API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.app_env == "production" else "/openapi.json",
        responses=error_responses,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = sessionmaker(engine, expire_on_commit=False)
    app.state.redis = redis
    app.state.email_sender = build_email(settings)
    app.state.google = GoogleOIDC(settings)
    app.include_router(router)
    app.include_router(google_router)
    app.include_router(credits_router)
    app.include_router(media_router)
    app.include_router(ai_router)
    app.include_router(rendering_router)
    app.add_exception_handler(ApiError, problem_response)  # type: ignore[arg-type]

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):  # type: ignore[no-untyped-def]
        return await problem_response(
            request, ApiError(422, "validation_failed", "Request fields are invalid.")
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):  # type: ignore[no-untyped-def]
        return await problem_response(
            request, ApiError(exc.status_code, "http_error", "Request could not be completed.")
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):  # type: ignore[no-untyped-def]
        return await problem_response(
            request, ApiError(503, "database_unavailable", "Service temporarily unavailable.")
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):  # type: ignore[no-untyped-def]
        logger.error(
            json.dumps({"request_id": request.state.request_id, "error_class": type(exc).__name__})
        )
        return await problem_response(
            request, ApiError(500, "internal_error", "Request could not be completed.")
        )

    @app.get("/health/live", response_model=Health, tags=["system"])
    def live() -> Health:
        return Health(status="alive")

    @app.get("/health/ready", response_model=Health, tags=["system"])
    def ready() -> Health:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1 FROM users LIMIT 1"))
            app.state.redis.ping()
        except Exception as exc:
            raise ApiError(503, "not_ready", "Dependencies or migrations unavailable.") from exc
        return Health(status="ready")

    # Wrapped in this order: request boundary -> CORS -> trusted host -> routes.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.public_app_url],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Content-Type",
            "X-CSRF-Token",
            "Idempotency-Key",
            "X-Content-SHA256",
            "If-Match",
        ],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestBoundary, production=settings.app_env == "production")
    return app
