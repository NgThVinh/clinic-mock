"""Tests for GET /health — no auth required."""

from tests.conftest import AUTH_A


def test_health_no_auth(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_with_auth(client):
    r = client.get("/health", headers=AUTH_A)
    assert r.status_code == 200


def test_health_has_request_id(client):
    r = client.get("/health")
    assert "x-request-id" in r.headers
