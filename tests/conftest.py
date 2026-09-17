"""Shared fixtures for clinic-mock API tests.

Uses FastAPI's TestClient (synchronous) with per-test DB reset so tests
are fully isolated.  Two tenants are seeded: `sk_test_a` and `sk_test_b`
to exercise data-isolation rules.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("MOCK_API_KEYS", "sk_test_a,sk_test_b")

from clinic_mock.app import create_app
from clinic_mock.auth import _registry, derive_tenant_id
from clinic_mock.store import db, seed_default


@pytest.fixture(autouse=True)
def _reset_db():
    _registry.cache_clear()
    seed_default()
    yield
    db.reset()


@pytest.fixture()
def app():
    _registry.cache_clear()
    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=False)


AUTH_A = {"Authorization": "Bearer sk_test_a"}
AUTH_B = {"Authorization": "Bearer sk_test_b"}
TENANT_A = derive_tenant_id("sk_test_a")
TENANT_B = derive_tenant_id("sk_test_b")


def idem_key() -> str:
    return f"idem_{uuid.uuid4().hex[:16]}"


def write_headers(version: int | None = None, key: str | None = None) -> dict:
    h: dict[str, str] = {}
    h["Idempotency-Key"] = key or idem_key()
    if version is not None:
        h["If-Match"] = str(version)
    return h
