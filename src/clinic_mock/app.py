from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from clinic_mock.auth import parse_bearer
from clinic_mock.config import settings
from clinic_mock.errors import ApiError, api_error_handler
from clinic_mock.logger import logger
from clinic_mock.routes import harness, v1
from clinic_mock.store import seed_default
from clinic_mock.tracing import instrument_app, setup_tracing


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_tracing()
    seed_default()
    logger.info("Clinic mock started on {}:{}", settings.app.HOST, settings.app.PORT)
    yield
    logger.info("Clinic mock shutting down.")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app.PROJECT_NAME,
        version=settings.app.VERSION,
        debug=settings.app.DEBUG,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        # 1. Assign a request id (echoed into the error envelope and trace attribute).
        rid = request.headers.get("X-Request-Id") or f"req_{uuid4().hex[:12]}"
        request.state.request_id = rid

        # Public docs endpoints skip auth.
        if request.url.path in {
            "/openapi.json",
            "/docs",
            "/docs/oauth2-redirect",
            "/redoc",
        }:
            response = await call_next(request)
            response.headers["X-Request-Id"] = rid
            return response

        # 2. Resolve bearer token → Principal (harness routes exempt).
        if not request.url.path.startswith("/_harness"):
            token = (
                request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            )
            if not token:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": {
                            "code": "UNAUTHORIZED",
                            "message": "Missing bearer token.",
                            "request_id": rid,
                        }
                    },
                    headers={"WWW-Authenticate": 'Bearer realm="clinic-mock"'},
                )
            try:
                request.state.principal = parse_bearer(token)
            except ValueError:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": {
                            "code": "UNAUTHORIZED",
                            "message": "Invalid bearer token.",
                            "request_id": rid,
                        }
                    },
                    headers={"WWW-Authenticate": 'Bearer realm="clinic-mock"'},
                )

        # Harness admin gets a synthetic principal so test runners don't need a key.
        elif request.url.path.startswith("/_harness"):
            from clinic_mock.auth import Principal

            request.state.principal = Principal(
                tenant_id="harness", api_key_last4="0000"
            )

        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return await api_error_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        rid = getattr(request.state, "request_id", None)
        details = [
            {"field": ".".join(str(p) for p in err["loc"]), "issue": err["msg"]}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed.",
                    "request_id": rid,
                    "details": details,
                }
            },
        )

    app.include_router(v1)
    app.include_router(harness)

    instrument_app(app)
    return app


# Module-level app for `uvicorn clinic_mock.app:app`
app = create_app()
