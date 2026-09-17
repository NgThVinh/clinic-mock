"""Standard error envelope and exception types."""

from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class ApiError(HTTPException):
    """HTTPException with a stable `code` and optional `details`."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.message = message
        self.details = details or []


# Common error factories — one-liners at call sites.


def validation_error(
    message: str, details: list[dict[str, Any]] | None = None
) -> ApiError:
    return ApiError(400, "INVALID_REQUEST", message, details=details)


def unauthorized() -> ApiError:
    """401 BAD_KEY per contract Appendix A. Function name kept for callers."""
    return ApiError(
        401,
        "BAD_KEY",
        "Missing or invalid bearer token.",
        headers={"WWW-Authenticate": 'Bearer realm="clinic-mock"'},
    )


def forbidden(scope: str) -> ApiError:
    return ApiError(
        403,
        "FORBIDDEN",
        f"Token lacks required scope: {scope}",
        headers={
            "WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{scope}"'
        },
    )


def not_found(what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} not found.")


def conflict(code: str, message: str) -> ApiError:
    return ApiError(409, code, message)


def version_conflict(current: int | None = None) -> ApiError:
    """409 VERSION_CONFLICT — If-Match header didn't match the current version."""
    details = [{"field": "version", "value": current}] if current is not None else None
    return ApiError(
        409,
        "VERSION_CONFLICT",
        "If-Match version does not match current state.",
        details=details,
    )


def confirmation_required(reason: str) -> ApiError:
    """409 CONFIRMATION_REQUIRED — §3.5 SF-05: cancel needs explicit second confirmation."""
    return ApiError(409, "CONFIRMATION_REQUIRED", reason)


def unprocessable(code: str, message: str) -> ApiError:
    return ApiError(422, code, message)


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body = {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "request_id": request_id,
        }
    }
    if exc.details:
        body["error"]["details"] = exc.details
    return JSONResponse(
        status_code=exc.status_code, content=body, headers=exc.headers or {}
    )


async def generic_http_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Map plain HTTPExceptions (e.g. raised by FastAPI itself) into the envelope."""
    request_id = getattr(request.state, "request_id", None)
    code_map = {
        401: "BAD_KEY",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
    }
    code = code_map.get(exc.status_code, "INTERNAL_ERROR")
    body = {
        "error": {"code": code, "message": str(exc.detail), "request_id": request_id}
    }
    return JSONResponse(
        status_code=exc.status_code, content=body, headers=exc.headers or {}
    )
