"""Bearer-token auth — single-key-per-tenant.

Env format: `MOCK_API_KEYS="tenant_id:sk_xxx,tenant_id:sk_yyy"`.

Every key starts with `sk_` and grants full access to its tenant — no
per-scope grant, no JWT. Mock-grade only; real auth would validate
HS256 signatures against an IDP, which is out of scope.

Harness routes (`/_harness/*`) are exempt; middleware assigns a synthetic
admin principal so test runners don't need a key.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from clinic_mock.config import settings

KEY_PREFIX = "sk_"

ALL_SCOPES = frozenset(
    {
        "patients:read",
        "slots:read",
        "appointments:read",
        "appointments:write",
        "calls:read",
        "calls:write",
        "harness:admin",
    }
)


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    api_key_last4: str

    def has(self, scope: str) -> bool:
        return True


@lru_cache(maxsize=1)
def _registry() -> frozenset[tuple[str, str]]:
    """Parse MOCK_API_KEYS into (api_key, tenant_id) pairs.

    Silently drops entries that don't carry the `sk_` prefix — typos in
    env shouldn't crash the mock; they're useless keys and stay unknown.
    """
    pairs: set[tuple[str, str]] = set()
    for raw in settings.mock_auth.API_KEYS.split(","):
        entry = raw.strip()
        if ":" not in entry:
            continue
        tenant_id, api_key = (p.strip() for p in entry.split(":", 1))
        if not (tenant_id and api_key.startswith(KEY_PREFIX)):
            continue
        pairs.add((api_key, tenant_id))
    return frozenset(pairs)


def _lookup_tenant(api_key: str) -> str | None:
    for k, t in _registry():
        if k == api_key:
            return t
    return None


def parse_bearer(token: str) -> Principal:
    if not token.startswith(KEY_PREFIX):
        raise ValueError(f"api key must start with {KEY_PREFIX}")
    tenant_id = _lookup_tenant(token)
    if tenant_id is None:
        raise ValueError("unknown api key")
    return Principal(tenant_id=tenant_id, api_key_last4=token[-4:])


def require_scope(request, scope: str) -> Principal:
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is None:
        from clinic_mock.errors import unauthorized

        raise unauthorized()
    return principal


def optional_principal(request) -> Principal | None:
    return getattr(request.state, "principal", None)
