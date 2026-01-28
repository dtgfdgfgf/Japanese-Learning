"""Error handling middleware for the API.

T024: Create error handling middleware in src/api/middleware.py
DoD: 未處理例外回傳 500 JSON 格式錯誤；request_id 記錄於 log
"""

import logging
import uuid
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware to add request ID to all requests."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Add request ID and handle exceptions.

        Args:
            request: Incoming request
            call_next: Next middleware/handler

        Returns:
            Response with request ID header
        """
        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        # Store in request state for use in handlers
        request.state.request_id = request_id

        # Add to logging context
        logger_extra = {"request_id": request_id}

        try:
            logger.info(
                f"Request started: {request.method} {request.url.path}",
                extra=logger_extra,
            )

            response = await call_next(request)

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id

            logger.info(
                f"Request completed: {response.status_code}",
                extra=logger_extra,
            )

            return response

        except Exception as e:
            logger.exception(
                f"Unhandled exception: {type(e).__name__}: {e}",
                extra=logger_extra,
            )

            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal Server Error",
                    "message": "An unexpected error occurred",
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id},
            )


def get_request_id(request: Request) -> str:
    """Get request ID from request state.

    Args:
        request: FastAPI request object

    Returns:
        Request ID string
    """
    return getattr(request.state, "request_id", "unknown")
