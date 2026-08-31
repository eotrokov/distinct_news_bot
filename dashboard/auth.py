from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response


class TokenAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == "/health" or self._is_authorized(request):
            return await call_next(request)
        return PlainTextResponse("Unauthorized", status_code=401)

    def _is_authorized(self, request: Request) -> bool:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip() == self._token
        query_token = request.query_params.get("token")
        if query_token and query_token == self._token:
            return True
        return False
