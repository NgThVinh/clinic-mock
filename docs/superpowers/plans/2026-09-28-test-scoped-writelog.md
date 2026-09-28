# Test-Scoped Writelog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a test harness scope every `/_harness/writelog` query to the time window of one test, and read/list captured snapshots — all without any new mock-side state model or new request headers.

**Architecture:** Three additive changes, all read-side. (1) `WriteLog.query` and the writelog route accept `since` / `until` ISO 8601 query params. (2) `Store.snapshot` stamps `tenant_id` + `created_at` on each snapshot, and a new `Store.get_snapshot` / `Store.list_snapshots` expose them per-tenant. (3) Two new routes: `GET /_harness/snapshot/{sid}` (read one) and `GET /_harness/snapshot` (list). No mock-side `test_id` field; harness correlates by the timestamps it captured around the test.

**Tech Stack:** Python 3.13, FastAPI 0.141+, Pydantic 2.13, FastAPI TestClient (pytest). ISO 8601 parsing via `datetime.fromisoformat`. Pytest for the suite.

**Spec:** `docs/superpowers/specs/2026-09-28-test-scoped-writelog-design.md`

## Global Constraints

- Time format: RFC 3339 UTC (`Z`) **or** `±HH:MM` offset. Existing `IsoDateTime` regex covers both — reuse it for query validation.
- Error codes: `INVALID_REQUEST` (400), `BAD_KEY` (401), `NOT_FOUND` (404) per Appendix A. Cross-tenant access returns `404 NOT_FOUND`, not `403 FORBIDDEN`.
- Tenant isolation: existing `_visible_tenants()` / `_writable_tenants()` helpers in `routes.py`. Snapshots are tenant-scoped (existence hidden).
- No new mock-side state for tests; harness keeps `t_start` / `t_end` / `snapshot_id` locally.
- All edits pass `ruff check src/ tests/` and `ruff format --check src/ tests/`.
- Per-task commits with `Co-Authored-By: Claude Code <noreply@anthropic.com>` footer.

## Review Focus

Five input classes the spec implies but that no single task's tests exercise directly. Each line says the input/condition and what behavior a reasonable person would expect; the test that pins each one is added to the task that owns the code.

1. **`since > until` validation.** Spec §1: "If both given and `since > until` → 400 INVALID_REQUEST." Owner: Task 1's `harness_writelog` route.
2. **Bad ISO timestamp.** Spec §1: "Bad input → 400 INVALID_REQUEST." Owner: Task 1 (route parser). Pydantic's auto-422 needs to be translated to 400 INVALID_REQUEST by the existing exception handler.
3. **Empty `since` and `until`.** Spec §1: "Empty filters retain current behavior." Owner: Task 1's writelog query — passing `None` for both must return everything in tenant scope (no error).
4. **Snapshot list with no snapshots in tenant.** Spec §3: "Returns the snapshots the caller's tenant owns." Owner: Task 2 — empty list returns `{snapshots: [], count: 0}` (200, not 404).
5. **Snapshot read with malformed `sid`.** Spec §2: nonexistent sid → 404. Owner: Task 2 — non-string or unknown sid both return 404 NOT_FOUND.

---

### Task 1: `WriteLog.query` accepts `since` / `until`; route wires the query params

**Files:**
- Modify: `src/clinic_mock/store.py:84-100` (extend `WriteLog.query`)
- Modify: `src/clinic_mock/routes.py:622-643` (extend `harness_writelog` query signature and parsing)
- Modify: `tests/test_harness.py` (add `TestWritelogTimeFilter` class)

**Interfaces:**
- Consumes: existing `WriteLog.query(op=None, appointment_id=None)` — keep signature backward-compatible by adding `since`, `until` after the existing kwargs.
- Produces: `WriteLog.query(op=None, appointment_id=None, since=None, until=None) -> list[dict]` — entries filtered by `entry["at"]` between `since.isoformat()` and `until.isoformat()` (inclusive).

**Spec mapping:** §1 (timestamp filters on writelog), §7 (+ reuses existing endpoints), §9 (e2e checks for `since`/`until`/both/both-empty/bad-ISO).

- [ ] **Step 1: Write failing tests in `tests/test_harness.py`**

Append a new test class. Read `tests/test_harness.py` first to find the right insertion point (after `TestHarnessSnapshot`) and to mirror its fixture usage. Use `AUTH_A` and `write_headers` from `tests/conftest.py`.

```python
class TestWritelogTimeFilter:
    def _seed_entries(self, client):
        # Three writes spread across ~3 distinct timestamps.
        sid = client.get("/_harness/snapshot", headers=AUTH_A).json()["snapshot_id"]
        client.post(
            "/v1/appointments/apt_00417/confirm",
            headers={**AUTH_A, **write_headers(3)},
        )
        first_at = client.get(
            "/_harness/writelog?op=confirm", headers=AUTH_A
        ).json()["entries"][0]["at"]
        client.post(
            "/v1/appointments/apt_00417/reschedule",
            headers={
                **AUTH_A,
                **write_headers(4),
                "Content-Type": "application/json",
            },
            json={"new_slot_id": "slot_91d2", "requested_by": "PATIENT"},
        )
        client.post(
            "/v1/appointments/apt_00417/cancel",
            headers={
                **AUTH_A,
                **write_headers(5),
                "Content-Type": "application/json",
            },
            json={"cancel_reason": "PATIENT_UNAVAILABLE", "confirmed": True},
        )
        return sid, first_at

    def test_writelog_filter_since(self, client):
        sid, first_at = self._seed_entries(client)
        r = client.get(
            f"/_harness/writelog?since={first_at}", headers=AUTH_A
        ).json()
        ops = [e["op"] for e in r["entries"]]
        assert ops == ["confirm", "reschedule", "cancel"]

    def test_writelog_filter_until_drops_later_entries(self, client):
        sid, first_at = self._seed_entries(client)
        # `until` between the first and second write — should drop reschedule/cancel.
        # Read the second entry's `at` and use a slightly earlier cutoff.
        all_entries = client.get("/_harness/writelog", headers=AUTH_A).json()["entries"]
        second_at = all_entries[1]["at"]
        # Truncate to second-precision so the cutoff sits between the two writes.
        cutoff = ".".join(second_at.split(".")[:-1])
        # Append `.999` to land AFTER the second entry's millisecond timestamp.
        until = second_at
        r = client.get(
            f"/_harness/writelog?until={until}", headers=AUTH_A
        ).json()
        ops = [e["op"] for e in r["entries"]]
        assert "reschedule" not in ops
        assert "cancel" not in ops
        assert "confirm" in ops

    def test_writelog_filter_since_and_until_window(self, client):
        sid, first_at = self._seed_entries(client)
        all_entries = client.get("/_harness/writelog", headers=AUTH_A).json()["entries"]
        second_at = all_entries[1]["at"]
        # Window: from the first write up to (and including) the second.
        r = client.get(
            f"/_harness/writelog?since={first_at}&until={second_at}",
            headers=AUTH_A,
        ).json()
        ops = [e["op"] for e in r["entries"]]
        assert ops == ["confirm", "reschedule"]

    def test_writelog_no_filters_returns_all(self, client):
        self._seed_entries(client)
        r = client.get("/_harness/writelog", headers=AUTH_A).json()
        assert r["count"] == 3

    def test_writelog_bad_iso_returns_400_invalid_request(self, client):
        r = client.get(
            "/_harness/writelog?since=not-a-date", headers=AUTH_A
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "INVALID_REQUEST"

    def test_writelog_since_greater_than_until_returns_400(self, client):
        r = client.get(
            "/_harness/writelog?since=2030-01-01T00:00:00Z&until=2020-01-01T00:00:00Z",
            headers=AUTH_A,
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "INVALID_REQUEST"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run python -m pytest tests/test_harness.py::TestWritelogTimeFilter -v
```

Expected: every test fails. The first three fail with `KeyError`/`AttributeError` (no `since` param). The last three fail with 200 / wrong code.

- [ ] **Step 3: Extend `WriteLog.query` in `src/clinic_mock/store.py`**

Locate `WriteLog.query` (around line 88) and replace it with:

```python
def query(
    self,
    op: str | None = None,
    appointment_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict]:
    out = self.entries
    if op is not None:
        out = [e for e in out if e.get("op") == op]
    if appointment_id is not None:
        out = [e for e in out if e.get("appointment_id") == appointment_id]
    if since is not None:
        since_iso = since.isoformat()
        out = [e for e in out if e.get("at", "") >= since_iso]
    if until is not None:
        until_iso = until.isoformat()
        out = [e for e in out if e.get("at", "") <= until_iso]
    return out
```

The ISO-string comparison works because `at` is already an ISO 8601 string produced by `now_iso()` in `app.py`. Lexicographic comparison is correct for ISO 8601 in the same timezone representation.

- [ ] **Step 4: Extend `harness_writelog` route in `src/clinic_mock/routes.py`**

Replace the route's signature/body (around line 622):

```python
@harness.get("/writelog", tags=["Admin"])
def harness_writelog(
    request: Request,
    op: Annotated[str | None, Query(description="Filter by op label")] = None,
    appointment_id: Annotated[
        str | None, Query(description="Filter by affected appointment id")
    ] = None,
    since: Annotated[
        datetime | None,
        Query(description="Inclusive lower bound (ISO 8601)."),
    ] = None,
    until: Annotated[
        datetime | None,
        Query(description="Inclusive upper bound (ISO 8601)."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=10000)] = 1000,
):
    """Append-only log of every /v1/* mutation since the last reset (§4.3 step 5).

    The scoring harness reads this to detect SF-01 (write to wrong appointment),
    SF-02 (offer slot not returned by /slots), and SF-05 (cancel without the
    second confirmation — visible as a 409 entry). Captures request body,
    status, If-Match and Idempotency-Key on each write.

    Pass `since` / `until` (ISO 8601) to scope entries to a single test's
    time window — the harness brackets each test with `t_start` before the
    first turn and `t_end` after the last.
    """
    _tenant(request)  # auth gate
    if since is not None and until is not None and since > until:
        raise validation_error("'since' must be <= 'until'.")
    entries = db.writelog.query(
        op=op,
        appointment_id=appointment_id,
        since=since,
        until=until,
    )
    return {
        "entries": entries[:limit],
        "count": len(entries),
        "truncated": len(entries) > limit,
    }
```

Add `validation_error` to the existing `errors` import in routes.py (line ~22):

```python
from clinic_mock.errors import (
    ...
    validation_error,
    ...
)
```

Pydantic's auto-validation handles bad ISO (returns 422 → 400 INVALID_REQUEST via the existing `RequestValidationError` handler in `app.py:96-109`). The `since > until` check is custom.

- [ ] **Step 5: Run tests to confirm they pass**

```bash
uv run python -m pytest tests/test_harness.py::TestWritelogTimeFilter -v
```

Expected: all 6 tests pass.

- [ ] **Step 6: Run ruff and pytest full suite**

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run python -m pytest -q
```

Expected: ruff clean; pytest 110+ passed, 1 xfailed (existing).

- [ ] **Step 7: Commit**

```bash
git add src/clinic_mock/store.py src/clinic_mock/routes.py tests/test_harness.py
git commit -m "feat(writelog): add since/until ISO 8601 filters for test scoping

Lets the test harness scope GET /_harness/writelog to a single test's
time window without exposing test_id to the mock.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: Snapshot tenant scoping + `GET /_harness/snapshot/{sid}` and `GET /_harness/snapshot`

**Files:**
- Modify: `src/clinic_mock/store.py:122-156` (`Store.snapshot`, `Store.restore`, add `get_snapshot`, `list_snapshots`)
- Modify: `src/clinic_mock/routes.py:628-633` (update `harness_snapshot` to pass tenant), `660-664` (update `harness_snapshot_restore` to pass tenant)
- Modify: `src/clinic_mock/routes.py` (add `harness_snapshot_read` and `harness_snapshot_list` routes)
- Modify: `tests/test_harness.py` (extend `TestHarnessSnapshot`)

**Interfaces:**
- Consumes: `Store.snapshot()` (currently takes no args and returns a `sid`); `Store.restore(sid)` (currently takes only `sid`).
- Produces:
  - `Store.snapshot(tenant_id: str) -> str` — returns `sid`; internally stores `{tenant_id, created_at, data: {...}}`.
  - `Store.restore(sid: str, caller_tenant_id: str) -> None` — raises 404 if `snapshots[sid].tenant_id != caller_tenant_id`.
  - `Store.get_snapshot(sid: str, caller_tenant_id: str) -> dict | None` — returns `{"snapshot_id", "created_at", "patients", "slots", "appointments", "writelog", "system_clock_offset_sec"}` or `None`.
  - `Store.list_snapshots(caller_tenant_id: str, since: datetime | None = None, until: datetime | None = None) -> list[dict]` — returns `[{snapshot_id, created_at}, ...]`.

**Spec mapping:** §2 (snapshot read), §3 (snapshot list with `since`/`until`), §4 (data model — `tenant_id`, `created_at`; cross-tenant 404), §9 (e2e checks for tenant scope).

- [ ] **Step 1: Write failing tests in `tests/test_harness.py`**

Extend the existing `TestHarnessSnapshot` class. Read it first to find the right insertion point. Use `AUTH_A` (caller tenant) and `AUTH_B` (other tenant) from `tests/conftest.py`.

```python
class TestHarnessSnapshotRead:
    def test_read_snapshot_returns_captured_state(self, client):
        sid = client.get("/_harness/snapshot", headers=AUTH_A).json()["snapshot_id"]
        body = client.get(f"/_harness/snapshot/{sid}", headers=AUTH_A).json()
        assert body["snapshot_id"] == sid
        assert "created_at" in body
        # Canonical fixtures are visible to every caller — they're seeded on
        # every caller's tenant via _visible_tenants().
        appt_ids = {a["appointment_id"] for a in body["appointments"]}
        assert "apt_00417" in appt_ids
        # Tenant_id is server-side only — must NOT appear in the payload.
        assert "tenant_id" not in body

    def test_read_unknown_snapshot_returns_404(self, client):
        r = client.get("/_harness/snapshot/snap_does_not_exist", headers=AUTH_A)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"

    def test_read_cross_tenant_snapshot_returns_404(self, client):
        # Tenant A creates a snapshot.
        sid = client.get("/_harness/snapshot", headers=AUTH_A).json()["snapshot_id"]
        # Tenant B tries to read it — existence is hidden, 404.
        r = client.get(f"/_harness/snapshot/{sid}", headers=AUTH_B)
        assert r.status_code == 404

    def test_restore_cross_tenant_snapshot_returns_404(self, client):
        sid = client.get("/_harness/snapshot", headers=AUTH_A).json()["snapshot_id"]
        r = client.post(f"/_harness/snapshot/{sid}/restore", headers=AUTH_B)
        assert r.status_code == 404

    def test_restore_unknown_snapshot_returns_404(self, client):
        r = client.post(
            "/_harness/snapshot/snap_does_not_exist/restore", headers=AUTH_A
        )
        assert r.status_code == 404


class TestHarnessSnapshotList:
    def test_list_returns_only_caller_tenant_snapshots(self, client):
        # Tenant A creates two snapshots; tenant B creates one.
        client.get("/_harness/snapshot", headers=AUTH_A)
        client.get("/_harness/snapshot", headers=AUTH_A)
        client.get("/_harness/snapshot", headers=AUTH_B)
        a_ids = {
            s["snapshot_id"]
            for s in client.get("/_harness/snapshot", headers=AUTH_A).json()["snapshots"]
        }
        b_ids = {
            s["snapshot_id"]
            for s in client.get("/_harness/snapshot", headers=AUTH_B).json()["snapshots"]
        }
        assert len(a_ids) == 2
        assert len(b_ids) == 1
        assert a_ids.isdisjoint(b_ids)

    def test_list_empty_tenant_returns_empty_envelope(self, client):
        # Fresh tenant (no snapshots taken yet).
        body = client.get("/_harness/snapshot", headers=AUTH_B).json()
        assert body == {"snapshots": [], "count": 0}

    def test_list_each_entry_has_snapshot_id_and_created_at(self, client):
        client.get("/_harness/snapshot", headers=AUTH_A)
        s = client.get("/_harness/snapshot", headers=AUTH_A).json()["snapshots"][0]
        assert set(s.keys()) == {"snapshot_id", "created_at"}

    def test_list_since_until_filters_by_created_at(self, client):
        # Capture two snapshots with a small sleep between them.
        import time
        client.get("/_harness/snapshot", headers=AUTH_A)
        first_created_at = client.get(
            "/_harness/snapshot", headers=AUTH_A
        ).json()["snapshots"][0]["created_at"]
        time.sleep(0.05)
        client.get("/_harness/snapshot", headers=AUTH_A)
        all_ids = {
            s["snapshot_id"]
            for s in client.get("/_harness/snapshot", headers=AUTH_A).json()["snapshots"]
        }
        filtered = client.get(
            f"/_harness/snapshot?since={first_created_at}", headers=AUTH_A
        ).json()
        filtered_ids = {s["snapshot_id"] for s in filtered["snapshots"]}
        # Since is inclusive — first_created_at snapshot should appear, plus
        # any taken after.
        assert first_created_at.split(".")[0] in [
            s["created_at"].split(".")[0] for s in filtered["snapshots"]
        ]
        assert filtered_ids.issubset(all_ids)

    def test_list_bad_iso_returns_400(self, client):
        r = client.get(
            "/_harness/snapshot?since=not-a-date", headers=AUTH_A
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "INVALID_REQUEST"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run python -m pytest tests/test_harness.py::TestHarnessSnapshotRead tests/test_harness.py::TestHarnessSnapshotList -v
```

Expected: every test fails (no `harness_snapshot_read`, no `harness_snapshot_list`; cross-tenant restore returns 200 currently).

- [ ] **Step 3: Update `Store.snapshot` / `Store.restore` / add `get_snapshot` / `list_snapshots` in `src/clinic_mock/store.py`**

Replace the `snapshot` and `restore` methods (around lines 122-156) with:

```python
def snapshot(self, tenant_id: str) -> str:
    sid = self.new_id("snap")
    self.snapshots[sid] = {
        "tenant_id": tenant_id,
        "created_at": now_iso(),
        "data": {
            "patients": {
                k: v.model_dump(exclude={"tenant_id"})
                for k, v in self.patients.items()
            },
            "slots": {
                k: v.model_dump(exclude={"tenant_id"})
                for k, v in self.slots.items()
            },
            "appointments": {
                k: {
                    **v.model_dump(),
                    "tenant_id": v.tenant_id,
                    "slot_id": v.slot_id,
                    "provider_id": v.provider_id,
                }
                for k, v in self.appointments.items()
            },
            "writelog": list(self.writelog.entries),
            "system_clock_offset_sec": self.system_clock_offset_sec,
        },
    }
    return sid

def get_snapshot(self, sid: str, caller_tenant_id: str) -> dict | None:
    snap = self.snapshots.get(sid)
    if snap is None or snap["tenant_id"] != caller_tenant_id:
        return None
    return {
        "snapshot_id": sid,
        "created_at": snap["created_at"],
        **snap["data"],
    }

def list_snapshots(
    self,
    caller_tenant_id: str,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict]:
    out: list[dict] = []
    for sid, snap in self.snapshots.items():
        if snap["tenant_id"] != caller_tenant_id:
            continue
        if since is not None and snap["created_at"] < since.isoformat():
            continue
        if until is not None and snap["created_at"] > until.isoformat():
            continue
        out.append({"snapshot_id": sid, "created_at": snap["created_at"]})
    return out

def restore(self, sid: str, caller_tenant_id: str) -> None:
    snap = self.snapshots.get(sid)
    if snap is None:
        from clinic_mock.errors import not_found
        raise not_found(f"snapshot {sid}")
    if snap["tenant_id"] != caller_tenant_id:
        # Cross-tenant access — existence hidden, same convention as
        # appointments / patients / slots reads.
        from clinic_mock.errors import not_found
        raise not_found(f"snapshot {sid}")
    self.patients = {k: Patient(**v) for k, v in snap["data"]["patients"].items()}
    self.slots = {k: Slot(**v) for k, v in snap["data"]["slots"].items()}
    self.appointments = {
        k: Appointment(**v) for k, v in snap["data"]["appointments"].items()
    }
    self.writelog = WriteLog()
    self.writelog.entries = list(snap["data"].get("writelog", []))
    self.system_clock_offset_sec = snap["data"]["system_clock_offset_sec"]
```

The patient/slot snapshot exclusion (`exclude={"tenant_id"}`) drops `tenant_id` because the snapshot data is restored into a Store that's already scoped to the caller — no need to round-trip the marker field. Appointment keeps `tenant_id` because it's needed for restore-time Pydantic validation (existing constraint).

- [ ] **Step 4: Update `harness_snapshot` and `harness_snapshot_restore` in `src/clinic_mock/routes.py`**

Update the existing two routes (around lines 628-664):

```python
@harness.get("/snapshot", tags=["Admin"])
def harness_snapshot(request: Request):
    sid = db.snapshot(tenant_id=_tenant(request))
    return {"snapshot_id": sid}

@harness.post("/snapshot/{sid}/restore", tags=["Admin"])
def harness_snapshot_restore(request: Request, sid: str):
    db.restore(sid, caller_tenant_id=_tenant(request))
    return {"restored": sid}
```

- [ ] **Step 5: Add `harness_snapshot_read` and `harness_snapshot_list` routes**

Append these two routes immediately after `harness_snapshot_restore`:

```python
@harness.get("/snapshot/{sid}", tags=["Admin"])
def harness_snapshot_read(request: Request, sid: str):
    """Read a captured snapshot. Tenant-scoped — other tenants get 404."""
    body = db.get_snapshot(sid, caller_tenant_id=_tenant(request))
    if body is None:
        raise not_found(f"snapshot {sid}")
    return body


@harness.get("/snapshot", tags=["Admin"])
def harness_snapshot_list(
    request: Request,
    since: Annotated[
        datetime | None,
        Query(description="Inclusive lower bound on snapshot created_at."),
    ] = None,
    until: Annotated[
        datetime | None,
        Query(description="Inclusive upper bound on snapshot created_at."),
    ] = None,
):
    """List the caller's tenant's snapshots, optionally bounded by time."""
    _tenant(request)  # auth gate
    if since is not None and until is not None and since > until:
        raise validation_error("'since' must be <= 'until'.")
    snapshots = db.list_snapshots(
        caller_tenant_id=_tenant(request),
        since=since,
        until=until,
    )
    return {"snapshots": snapshots, "count": len(snapshots)}
```

Note: there are now **two** `@harness.get("/snapshot")` routes — the existing `POST /snapshot` (capture) and the new `GET /snapshot` (list). FastAPI dispatches by method, so they coexist on the same path.

`not_found` and `validation_error` must be in the existing `errors` import block — add `not_found` if not already there.

- [ ] **Step 6: Run the new tests**

```bash
uv run python -m pytest tests/test_harness.py::TestHarnessSnapshotRead tests/test_harness.py::TestHarnessSnapshotList tests/test_harness.py::TestHarnessSnapshot -v
```

Expected: all tests pass.

- [ ] **Step 7: Run full suite + ruff**

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run python -m pytest -q
```

Expected: ruff clean; pytest ~120 passed, 1 xfailed (existing).

- [ ] **Step 8: Commit**

```bash
git add src/clinic_mock/store.py src/clinic_mock/routes.py tests/test_harness.py
git commit -m "feat(snapshot): tenant-scope reads + GET /{sid} + GET / list

Snapshots now record tenant_id and created_at. New endpoints let a
test harness scope writes to a single test's time window without
exposing test_id to the mock. Cross-tenant snapshot access returns
404 NOT_FOUND (existence hidden).

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: Doc updates — `docs/openapi.yaml` and `docs/APIs.md`

**Files:**
- Modify: `docs/openapi.yaml` (add two paths, two query params, one schema field)
- Modify: `docs/APIs.md` (add §4.2 about the time-scoped workflow)

**Spec mapping:** §1–§3 (new endpoints and params), §5 (workflow), §6 (harness derivations table).

- [ ] **Step 1: Update `docs/openapi.yaml`**

Read the existing file first. Add these additions:

**(a)** In the `writelog` path (around line 380), add two new query parameters to the operation:

```yaml
parameters:
  # existing op / appointment_id / limit params stay
  - { in: query, name: since, schema: { type: string, format: date-time }, description: 'Inclusive lower bound on entry `at` (ISO 8601). Used to scope a query to one test''s time window.' }
  - { in: query, name: until, schema: { type: string, format: date-time }, description: 'Inclusive upper bound on entry `at` (ISO 8601).' }
```

**(b)** Add a new path `/_harness/snapshot/{sid}` (alongside the existing `/_harness/snapshot` POST):

```yaml
/_harness/snapshot/{sid}:
  parameters:
    - { in: path, name: sid, required: true, schema: { type: string } }
  get:
    tags: [Admin]
    operationId: harnessSnapshotRead
    summary: Read a captured snapshot. Tenant-scoped.
    security:
      - bearerAuth: []
    responses:
      '200':
        description: The snapshot.
        content:
          application/json:
            schema:
              type: object
              required: [snapshot_id, created_at, patients, slots, appointments, writelog]
              properties:
                snapshot_id: { type: string }
                created_at: { type: string, format: date-time }
                patients:
                  type: array
                  items: { $ref: '#/components/schemas/Patient' }
                slots:
                  type: array
                  items: { $ref: '#/components/schemas/Slot' }
                appointments:
                  type: array
                  items: { $ref: '#/components/schemas/Appointment' }
                writelog:
                  type: array
                  items: { $ref: '#/components/schemas/WriteLogEntry' }
                system_clock_offset_sec: { type: integer }
      '401': { $ref: '#/components/responses/BadKey' }
      '404': { $ref: '#/components/responses/NotFound' }
```

**(c)** Update the existing `GET /_harness/snapshot` definition (currently no GET exists; only POST). Add a `get:` block alongside the existing `post:`:

```yaml
get:
  tags: [Admin]
  operationId: harnessSnapshotList
  summary: List the caller's tenant's snapshots, optionally bounded by `since`/`until`.
  security:
    - bearerAuth: []
  parameters:
    - { in: query, name: since, schema: { type: string, format: date-time } }
    - { in: query, name: until, schema: { type: string, format: date-time } }
  responses:
    '200':
      description: Caller's snapshots.
      content:
        application/json:
          schema:
            type: object
            required: [snapshots, count]
            properties:
              snapshots:
                type: array
                items:
                  type: object
                  required: [snapshot_id, created_at]
                  properties:
                    snapshot_id: { type: string }
                    created_at: { type: string, format: date-time }
              count: { type: integer }
    '400': { $ref: '#/components/responses/InvalidRequest' }
    '401': { $ref: '#/components/responses/BadKey' }
```

- [ ] **Step 2: Update `docs/APIs.md`**

Append a new sub-section inside `## 4. Admin & Operations` (right after `### 4.2 Writelog`):

```markdown
### 4.3 Time-scoped test queries (§4.3 step 5)

The harness drives one test at a time. To scope the writelog and snapshots
to that test, bracket it with timestamps and snapshot before/after. Every
write+read the bot made during the test, plus a "before" view, comes back
over four GETs:

```bash
# Setup
SID=$(curl -sX POST "$HOST/_harness/snapshot" -H "$AUTH" | jq -r .snapshot_id)
T_START=$(now_iso)   # harness keeps this locally

# Drive the test (contract §4.3 figure 2)
curl -sX POST "$BOT/v1/calls" -d '{...}'                       # → call_id (on bot)
curl -sX POST "$BOT/v1/calls/$CALL_ID/turn" -d '{...}' × N     # bot hits /v1/* internally

T_END=$(now_iso)

# Verify — everything-for-test-X
curl -s "$HOST/_harness/writelog?since=$T_START&until=$T_END" -H "$AUTH"
curl -s "$HOST/_harness/snapshot/$SID" -H "$AUTH"
curl -s "$HOST/_harness/state" -H "$AUTH"
```

`GET /_harness/snapshot/{sid}` returns the snapshot's contents; the harness
diffs against `/_harness/state` to find what changed.

`GET /_harness/snapshot` lists the caller's snapshots, optionally bounded
by `?since=<iso>&until=<iso>` (both inclusive on `created_at`). Useful for
cleanup; not required if the harness tracks ids externally.

Both snapshot read endpoints are tenant-scoped: cross-tenant access returns
`404 NOT_FOUND` (existence hidden). Bad ISO timestamps return
`400 INVALID_REQUEST`. `since > until` returns `400 INVALID_REQUEST`.
```

- [ ] **Step 3: Validate the openapi.yaml**

```bash
uv run python -c "
import yaml
spec = yaml.safe_load(open('docs/openapi.yaml'))
paths = list(spec['paths'].keys())
assert '/_harness/snapshot' in paths, 'snapshot list endpoint missing'
assert '/_harness/snapshot/{sid}' in paths, 'snapshot read endpoint missing'
writelog_op = spec['paths']['/_harness/writelog']['get']
params = {p['name'] for p in writelog_op.get('parameters', [])}
assert 'since' in params and 'until' in params, 'writelog since/until missing'
print('openapi.yaml OK')
"
```

Expected: `openapi.yaml OK`.

- [ ] **Step 4: Commit**

```bash
git add docs/openapi.yaml docs/APIs.md
git commit -m "docs: time-scoped test queries — writelog since/until, snapshot read/list

Documents the four-Get workflow for assembling 'everything for test X':
capture snapshot, drive test, query writelog with since/until, read
snapshot, read state.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: Final end-to-end verification

**Files:**
- Modify: `/tmp/verify_contract.py` (add end-to-end time-scoping checks)
- No code changes — this task validates the others.

**Spec mapping:** §9 (verification plan).

- [ ] **Step 1: Append end-to-end checks to `/tmp/verify_contract.py`**

Add a new section after the existing `/_harness/writelog (§4.3 step 5)` block. Find the `print("\nTenant isolation + canonical sharing")` line and insert the new block before it:

```python
print("\nTime-scoped test queries (§4.3 step 5)")

reset()
KEY = "sk_test_aaa"
H = "http://localhost:8000"
AUTH = {"Authorization": f"Bearer {KEY}"}

# Simulate one full test: capture snapshot, drive, scope queries.
sid = httpx.post(f"{H}/_harness/snapshot", headers=AUTH).json()["snapshot_id"]
t_start = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

# Drive the test: read slots, then write a reschedule.
httpx.get(
    f"{H}/v1/slots",
    params={"clinic_id": "cl_vinmec", "from": "2026-10-14T00:00:00Z", "to": "2026-10-15T00:00:00Z"},
    headers=AUTH,
)
httpx.post(
    f"{H}/v1/appointments/apt_00417/reschedule",
    headers={**AUTH, "Content-Type": "application/json", "If-Match": "3"},
    json={"new_slot_id": "slot_91d2", "requested_by": "PATIENT"},
).raise_for_status()

t_end = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

# 1. Writelog scoped to the test window.
scoped = httpx.get(
    f"{H}/_harness/writelog", params={"since": t_start, "until": t_end}, headers=AUTH
).json()
check(
    "Time-scoped writelog returns only the test's writes+reads",
    set(e["op"] for e in scoped["entries"]) == {"list_slots", "reschedule"},
    f"got ops={[e['op'] for e in scoped['entries']]}",
)
check(
    "Time-scoped writelog preserves chronological order",
    [e["op"] for e in scoped["entries"]] == ["list_slots", "reschedule"],
)

# 2. Read the captured snapshot.
snap_body = httpx.get(f"{H}/_harness/snapshot/{sid}", headers=AUTH)
check(
    "GET /_harness/snapshot/{sid} returns 200",
    snap_body.status_code == 200,
)
snap = snap_body.json()
check(
    "Snapshot body has created_at and snapshot_id but no tenant_id",
    "created_at" in snap and "snapshot_id" in snap and "tenant_id" not in snap,
)
check(
    "Snapshot's writelog field is empty (nothing happened before t_start)",
    snap["writelog"] == [],
)

# 3. Cross-tenant snapshot read returns 404.
KEY2 = "sk_test_bbb"
cross = httpx.get(f"{H}/_harness/snapshot/{sid}", headers={"Authorization": f"Bearer {KEY2}"})
check(
    "Cross-tenant snapshot read returns 404 (existence hidden)",
    cross.status_code == 404,
)

# 4. List returns own tenant's snapshots.
list_body = httpx.get(f"{H}/_harness/snapshot", headers=AUTH).json()
check(
    "GET /_harness/snapshot list returns own tenant's snapshots",
    any(s["snapshot_id"] == sid for s in list_body["snapshots"]),
)

# 5. Bad ISO returns 400.
bad = httpx.get(f"{H}/_harness/writelog?since=not-a-date", headers=AUTH)
check(
    "Bad ISO on writelog since returns 400 INVALID_REQUEST",
    bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_REQUEST",
)

# 6. since > until returns 400.
inverted = httpx.get(
    f"{H}/_harness/writelog?since=2030-01-01T00:00:00Z&until=2020-01-01T00:00:00Z",
    headers=AUTH,
)
check(
    "since > until returns 400 INVALID_REQUEST",
    inverted.status_code == 400 and inverted.json()["error"]["code"] == "INVALID_REQUEST",
)
```

Add the missing imports at the top of `/tmp/verify_contract.py` if not already present:

```python
from datetime import UTC, datetime
```

- [ ] **Step 2: Run the full verification**

```bash
pkill -9 -f "uv run dev" 2>/dev/null; sleep 1
nohup uv run dev > /tmp/clinic-mock.log 2>&1 &
disown
sleep 4
uv run python /tmp/verify_contract.py 2>&1 | tail -10
```

Expected: `=== NN pass, 0 fail ===` with NN ≥ 87 (previous 81 + 6 new checks).

- [ ] **Step 3: Run ruff + pytest full suite**

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run python -m pytest -q
```

Expected: ruff clean; pytest ~120 passed, 1 xfailed.

- [ ] **Step 4: Stop dev server**

```bash
pkill -f "uv run dev"
```

- [ ] **Step 5: Final commit (if any review-driven tweaks landed)**

If the previous tasks left the tree clean, this step is a no-op. Otherwise:

```bash
git status
git diff
# stage and commit only the necessary fixes
```

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-28-test-scoped-writelog.md`. Please review the plan. Does it capture what you want?

For execution, the plan is short (4 tasks, ~12 incremental commits, no parallelism between tasks) and each task has its own test gate. **I recommend subagent-driven execution**, because each task's tests pin a distinct contract clause and a fresh reviewer per task catches regressions before they propagate.

If you prefer native (I implement all tasks in this session, then one reviewer checks the whole branch), say so.

Which execution approach should we use?
