# Test-Scoped Writelog Query — Design Spec

**Date:** 2026-09-28
**Status:** Draft (awaiting user review)
**Scope:** clinic-mock — additions only, no new state model.

## Context

The clinic-mock is the API surface that an AI callbot calls into during tests.
Today, every test a harness drives writes to a single global writelog
(`GET /_harness/writelog`), and the only way to scope "what happened during
test X" is to read the entire log and filter client-side by timestamp.

The user wants the harness to answer **"give me everything for test X in one
query"** — chronologically-ordered writes + reads the bot made, plus final
state, plus a "before" view to diff against. Tests are identified by the
bot's `call_id`, but the bot issues that id and the clinic-mock never sees
`POST /v1/calls` (those live on the bot, contract §4.1). So the mock must
either learn the test id somehow, or let the harness correlate side-channel.

Per brainstorming, **side-channel correlation** won: the mock stays a
passive recorder; the harness keeps `t_start` / `t_end` timestamps per test
and asks the mock for the relevant slices.

## Design summary

Three additions to the existing surface, all read-side:

1. `GET /_harness/writelog` — add `since` / `until` ISO 8601 timestamp filters.
2. `GET /_harness/snapshot/{sid}` — read a captured snapshot (currently only
   `POST .../restore` exists; the read is missing).
3. `GET /_harness/snapshot` — list snapshot ids (small, lets the harness
   discover and clean up without tracking ids externally).

Plus one internal change: snapshots get a `tenant_id` so the read endpoints
can be tenant-scoped (see §4).

No new endpoints beyond the above three. No new mock-side state.
No new headers. No session lifecycle.

## 1. `GET /_harness/writelog` — timestamp filters

Add `since` and `until` query parameters. Both optional.

| Param | Type | Meaning |
|---|---|---|
| `since` | ISO 8601 string | include only entries with `at >= since` |
| `until` | ISO 8601 string | include only entries with `at <= until` |
| `op` (existing) | string | filter by op label |
| `appointment_id` (existing) | string | filter by affected appointment id |
| `limit` (existing) | int 1..10000 | cap returned entries |

Filter order: timestamp → op → appointment_id → limit.

Validation:
- `since` and `until` must be parseable as ISO 8601. Bad input → `400 INVALID_REQUEST`.
- If both given and `since > until` → `400 INVALID_REQUEST`.
- Empty filters retain current behavior (return everything in tenant scope).

Response shape unchanged: `{entries: [...], count: int, truncated: bool}`.

Implementation: extend `WriteLog.query()` (in `store.py`) with optional
`since: datetime | None` and `until: datetime | None` params. Parse ISO
strings in the route, pass `datetime` objects down.

## 2. `GET /_harness/snapshot/{sid}` — read a snapshot

Currently only `POST /_harness/snapshot/{sid}/restore` exists. Add a read
that returns the snapshot's contents:

```json
{
  "snapshot_id": "snap_xxx",
  "created_at": "2026-09-28T...",
  "patients":     [...],
  "slots":        [...],
  "appointments": [...],
  "writelog":     [...],
  "system_clock_offset_sec": 0
}
```

`tenant_id` is **not** returned (server-side scoping only, same as the
existing convention for appointments/slots/patients). The `created_at`
is the wall-clock time the snapshot was captured (used by the harness to
correlate with its `t_start`).

Tenant-scoped (see §4): a caller's request to read another tenant's
snapshot returns `404 NOT_FOUND` (existence hidden, same convention as
cross-tenant appointment reads).

## 3. `GET /_harness/snapshot` — list snapshots

Returns the snapshots the caller's tenant owns:

```json
{
  "snapshots": [
    {"snapshot_id": "snap_xxx", "created_at": "2026-09-28T..."},
    ...
  ],
  "count": int
}
```

Optional query: `?since=<iso>`, `?until=<iso>` to bound the list to
snapshots captured in a time window (useful when many tests run in a row).
`since` / `until` are inclusive on both ends; bad ISO → `400 INVALID_REQUEST`.

## 4. Data model change — `tenant_id` on snapshots

Snapshots today are stored as a single dict on the Store instance
(`self.snapshots: dict[str, dict]`) with no tenant association. To scope
reads, attach a `tenant_id` at capture time.

Implementation:
- `Store.snapshot()` returns `(sid, tenant_id, snapshot_dict)`. The
  `tenant_id` is the caller that invoked `POST /_harness/snapshot`.
- `self.snapshots[sid]` stores `{"tenant_id": ..., "data": snapshot_dict}`.
- `Store.restore(sid, caller_tenant_id)`: if `self.snapshots[sid].tenant_id`
  ≠ `caller_tenant_id` → `404 NOT_FOUND`.
- New `Store.get_snapshot(sid, caller_tenant_id) -> dict | None` returns
  the snapshot data (without `tenant_id` leaking) or `None` if not
  visible to the caller.

Wire into the existing harness auth path: `harness_snapshot`,
`harness_snapshot_restore`, and the new read endpoints all use the
caller's `tenant_id` from `_tenant(request)`.

## 5. Harness workflow

A typical test loop:

```bash
# Setup
SID=$(curl -sX POST "$H/_harness/snapshot" $AUTH | jq -r .snapshot_id)
T_START=$(now_iso)   # harness keeps this locally

# Drive the test on the bot (contract §4.3)
curl -sX POST "$BOT/v1/calls" -d '{...}'                       # → call_id
curl -sX POST "$BOT/v1/calls/$CALL_ID/turn" -d '{...}' × N     # bot hits /v1/* internally

T_END=$(now_iso)

# Verify — everything-for-test-X is 4 GETs against clinic-mock
curl -s "$H/_harness/writelog?since=$T_START&until=$T_END" $AUTH   # writes + reads, in order
curl -s "$H/_harness/snapshot/$SID" $AUTH                        # before state
curl -s "$H/_harness/state" $AUTH                                # after state
# Diff before vs after in harness code → finds what changed
```

## 6. What the harness can now derive

| Question | How |
|---|---|
| Did the bot call `/slots` and what was served? | `writelog` entry with `op=list_slots`, body has `data[*].slot_id` |
| Did the bot book a slot it wasn't served? (SF-02) | intersect booked slot_id (write entry body) with served slot_ids (read entries before that write) |
| Did the bot write to the right appointment? (SF-01) | filter writelog entries by `appointment_id`, compare to the call's named appointment |
| Did the bot cancel without second confirmation? (SF-05) | find any `op=cancel` 200 entry without a prior `op=cancel` 409 entry |
| Final appointment state | `state` (or `/v1/appointments/{id}`) |
| Slot pool before / after | diff `snapshot/{sid}.slots` vs `state.slots` |
| What patient did the bot identify? | `writelog` entries with `op=find_patients`, body has `data[*].patient_id` |

## 7. Trade-offs

- **+** Mock stays a passive recorder — no new state machine, no session lifecycle, no new headers.
- **+** Reuses existing endpoints (`/state`, `/snapshot`, `/writelog`) with minimal additions.
- **+** Snapshot reads are tenant-scoped — preserves the existing isolation guarantees.
- **−** Harness must keep `t_start` / `t_end` and the snapshot id locally; if it loses them, correlation is lost.
- **−** Sequential tests only — concurrent tests in one tenant would need a stronger mechanism. (Contract §4.3 is sequential; not a blocker.)
- **−** A small amount of harness state per test (t_start, t_end, snapshot_id) is required; the mock doesn't carry any of this.

## 8. Out of scope

- Concurrent test execution within one tenant.
- Mock-side tagging of writes with an explicit `test_id` field (explicitly rejected via side-channel choice).
- A composite `/harness/test/{id}/summary` endpoint — the harness already has the four GETs it needs and is in a better position to assemble the report.
- New auth/headers for binding — explicitly rejected via side-channel choice.

## 9. Verification plan

- Unit-style e2e checks (added to `/tmp/verify_contract.py`):
  - `?since=` alone, `?until=` alone, both together, both empty.
  - `since > until` → `400 INVALID_REQUEST`.
  - Bad ISO → `400 INVALID_REQUEST`.
  - `GET /_harness/snapshot/{sid}` returns the same shape the harness
    captured.
  - `GET /_harness/snapshot` lists only the caller's tenant's snapshots.
  - Cross-tenant read of snapshot → `404 NOT_FOUND`.
  - End-to-end: capture snapshot → run a test (writes + reads) → query
    by `since`/`until` → assert the returned entries match the test.

## 10. Files touched

- `src/clinic_mock/store.py` — add `tenant_id` to snapshot, add
  `get_snapshot` and `list_snapshots` (with optional time filter).
- `src/clinic_mock/routes.py` — add `since`/`until` to
  `harness_writelog`; add `harness_snapshot_read` (GET /{sid}); add
  `harness_snapshot_list` (GET /).
- `docs/openapi.yaml` — document the two new query params and the two
  new endpoints.
- `docs/APIs.md` — describe the four-Get "everything for test X" workflow.
- `tests/test_harness.py` — pytest coverage for the new endpoints
  (tenant scoping, time-window filtering).

## 11. Non-goals

- Not changing the writelog entry shape (no `test_id` field).
- Not adding a session/begin-end state machine.
- Not changing per-tenant isolation semantics beyond snapshot reads.
- Not touching the bot's `/v1/calls/*` surface — those belong to the bot, contract §4.1.
