"""Bearer-token auth — single-key-per-tenant.

Env format: `MOCK_API_KEYS="sk_xxx,sk_yyy"` (or the legacy
`"tenant_id:sk_xxx,tenant_id:sk_yyy"` for explicit tenant mapping).

Each key resolves to exactly one `tenant_id`:
  * explicit form — tenant_id is taken from the env entry verbatim
  * bare form — tenant_id is auto-derived as `t_<sha256(key)[:8]>`, stable
    across restarts, opaque, and unique per key

Every key starts with `sk_` and grants full access to its tenant — no
per-scope grant, no JWT. Mock-grade only; real auth would validate
HS256 signatures against an IDP, which is out of scope.

All routes (including `/_harness/*`) require auth. Cross-tenant reads
return `404 NOT_FOUND` rather than `403 FORBIDDEN` so existence is hidden.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache

from clinic_mock.config import settings

KEY_PREFIX = "sk_"


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    api_key_last4: str


def derive_tenant_id(api_key: str) -> str:
    """Stable, opaque tenant id derived from the key. Public so callers (e.g.
    seed fixtures) can compute the same id without going through the registry.
    """
    return "t_" + hashlib.sha256(api_key.encode()).hexdigest()[:8]


@lru_cache(maxsize=1)
def _registry() -> frozenset[tuple[str, str]]:
    """Parse MOCK_API_KEYS into (api_key, tenant_id) pairs.

    Silently drops entries that don't carry the `sk_` prefix — typos in
    env shouldn't crash the mock; they're useless keys and stay unknown.
    """
    pairs: set[tuple[str, str]] = set()
    for raw in settings.mock_auth.API_KEYS.split(","):
        entry = raw.strip()
        if not entry:
            continue
        if ":" in entry:
            tenant_id, api_key = (p.strip() for p in entry.split(":", 1))
        else:
            api_key = entry
            tenant_id = derive_tenant_id(api_key)
        if api_key.startswith(KEY_PREFIX) and tenant_id:
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


def optional_principal(request) -> Principal | None:
    return getattr(request.state, "principal", None)
