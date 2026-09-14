import uvicorn

from clinic_mock.config import settings


def _serve(reload: bool) -> None:
    uvicorn.run(
        "clinic_mock.app:app",
        host=settings.app.HOST,
        port=settings.app.PORT,
        reload=reload,
        log_level="debug" if reload else "info",
    )


def run_dev() -> None:
    """Entry point for `uv run dev` — hot reload, debug logging."""
    _serve(reload=True)


def run_prod() -> None:
    """Entry point for `uv run prod` — single process, production logging."""
    _serve(reload=False)
