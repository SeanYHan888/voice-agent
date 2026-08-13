"""Request-scoped logging.

Each request gets an id that follows it across service boundaries via `X-Request-Id`, so a
single caller turn can be traced through gateway → agent → domain in the logs — the
counterpart to the LangFuse trace, which covers reasoning rather than plumbing.
"""
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

log = logging.getLogger("request")


class RequestLogMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, service: str):
        super().__init__(app)
        self.service = service

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "%s %s %s failed rid=%s", self.service, request.method, request.url.path, request_id
            )
            raise

        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        log.info(
            "%s %s %s -> %s %sms rid=%s",
            self.service,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
        response.headers["X-Request-Id"] = request_id
        return response
