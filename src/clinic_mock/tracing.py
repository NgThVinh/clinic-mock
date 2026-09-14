"""Langfuse + OpenTelemetry setup.

Uses Langfuse's built-in OTel auto-instrumentation so FastAPI requests emit
`http.server.request` spans with the attributes spelled out in APIs.md §14.2.
Tests should never read traces via this API — they read from Langfuse directly.
"""

from __future__ import annotations

import os

from clinic_mock.config import settings
from clinic_mock.logger import logger


def setup_tracing() -> None:
    """Idempotent tracer init. Returns silently if traces are disabled."""
    if not settings.langfuse.TRACES_ENABLED:
        logger.info("Langfuse traces disabled (LANGFUSE_TRACES_ENABLED=false).")
        return
    if not (settings.langfuse.PUBLIC_KEY and settings.langfuse.SECRET_KEY):
        logger.warning("Langfuse credentials missing; skipping trace setup.")
        return

    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse.PUBLIC_KEY)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse.SECRET_KEY)
    os.environ.setdefault("LANGFUSE_HOST", settings.langfuse.HOST)

    try:
        # Langfuse SDK wires its exporter into the global OTel TracerProvider.
        from langfuse import Langfuse  # noqa: F401

        Langfuse(environment=settings.langfuse.ENVIRONMENT)

        # FastAPIInstrumentor is enabled later in app.py once the app exists.
        logger.info(
            "Langfuse initialized: host={} env={}",
            settings.langfuse.HOST,
            settings.langfuse.ENVIRONMENT,
        )
    except Exception as exc:  # noqa: BLE001 — observability must never break the app
        logger.warning("Langfuse setup failed: {}", exc)


def instrument_app(app) -> None:
    """Attach FastAPI OTel instrumentation to the live FastAPI app."""
    if not settings.langfuse.TRACES_ENABLED:
        return
    if not (settings.langfuse.PUBLIC_KEY and settings.langfuse.SECRET_KEY):
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:  # noqa: BLE001
        logger.warning("FastAPI OTel instrumentation failed: {}", exc)
