# Clinic Platform API Specification

Version: **v1** (stable) · Last revised: 2026-09-14 · Companion: [`openapi.yaml`](openapi.yaml) · [`CHANGELOG.md`](CHANGELOG.md)

## 0. Overview

The Clinic Platform API is a public, versioned HTTP API in two clearly-scoped surfaces on the same base URL:

* **Appointment API** — booking and lifecycle of medical appointments.
* **Calls API** — voice-agent call lifecycle (start, identity verification state, escalation to staff, no-answer logging, end).

This document is the authoritative human-readable contract; the companion [`openapi.yaml`](openapi.yaml) is the machine-readable form and source of truth for client tooling.

| Property | Value |
| :--- | :--- |
| Base URL (production) | `https://api.clinic.example/v1` |
| Base URL (sandbox) | `https://sandbox.api.clinic.example/v1` |
| Transport | HTTPS only; HTTP requests are rejected at the edge. |
| Encoding | `Content-Type: application/json; charset=utf-8` |
| Stability | `v1` is stable. Breaking changes ship as `v2`; non-breaking additions ship within `v1`. |
| Deprecation window | 12 months minimum after a route is first advertised with `Sunset`. |
| Time format | RFC 3339 / ISO-8601 in UTC with `Z` suffix; date-only fields are `YYYY-MM-DD`. |

## 1. Conventions

### 1.1 Request Headers

| Header | Required | Description |
| :--- | :--- | :--- |
| `Authorization` | yes (except `/_harness/*`) | `Bearer <api_key>` — see [Authentication](#2-authentication). |
| `Content-Type` | on requests with a body | Must be `application/json; charset=utf-8`. |
| `Accept-Version` | recommended | API version; defaults to `v1` if absent — see [Versioning](#3-versioning). |
| `Idempotency-Key` | recommended on `POST` | Stable per-tenant key for safe replays — see [Idempotency](#8-idempotency). |
| `X-Request-Id` | recommended | Client-supplied correlation id (UUIDv4). Echoed in the response, error envelope, and emitted as the `langfuse.request.id` attribute on every trace. |

### 1.2 Response Headers (every response)

| Header | Description |
| :--- | :--- |
| `Content-Type` | `application/json; charset=utf-8` |
| `X-Request-Id` | Server-issued if the client omitted one. |
| `X-RateLimit-*` | Current bucket state — see [Rate Limiting](#6-rate-limiting). |

## 2. Authentication

The mock uses **mock-grade bearer-token auth**: a single API key per tenant, no JWT, no signature, no per-scope grants. Every valid key has full access to its tenant. A real implementation would validate HS256 signatures against an IDP — out of scope for this mock.

### 2.1 Request

All endpoints under `/v1/...` require a bearer token. `/_harness/*`, `/health`, and the docs endpoints (`/docs`, `/openapi.json`, `/redoc`) skip auth.

```
Authorization: Bearer <api_key>
```

* `<api_key>` must start with the prefix `sk-`.
* Keys are registered via the `MOCK_API_KEYS` env var as a comma-separated list of `tenant_id:sk-xxx` entries.
* No expiration, no rotation, no revocation — a key is valid for as long as it is present in `MOCK_API_KEYS` and is removed only by editing the env.
* The default seed is `tenant_demo:sk-dev-demo` so the mock is usable out-of-the-box.

### 2.2 Failure Modes

| HTTP | Code | When | Response Header |
| :---: | :--- | :--- | :--- |
| `401` | `UNAUTHORIZED` | Token missing, malformed (no `sk-` prefix), or unknown to `MOCK_API_KEYS`. | `WWW-Authenticate: Bearer realm="clinic-mock"` |

`403 FORBIDDEN` is **defined** for the future case of per-scope grants, but the mock does not currently enforce per-scope checks — every valid key passes every scope guard, so `403` is unreachable today.

### 2.3 Scopes (declared, not enforced)

These scopes are the conceptual access boundaries the mock uses to label endpoints. They are **not enforced** at runtime — `require_scope(...)` only verifies that a valid key was presented, not which scopes the key carries.

| Scope | Endpoint Group |
| :--- | :--- |
| `patients:read` | `GET /patients` |
| `slots:read` | `GET /slots` |
| `appointments:read` | `GET /appointments`, `GET /appointments/{id}` |
| `appointments:write` | `POST /appointments` and all `POST /appointments/{id}/...` |
| `calls:read` | `GET /calls`, `GET /calls/{id}` |
| `calls:write` | `POST /calls`, `PATCH /calls/{id}`, `POST /calls/{id}/escalate`, `POST /calls/{id}/attempts`, `POST /calls/{id}/end` |
| `harness:admin` | `GET` and `POST` under `/_harness/*` (auth-exempt; synthetic principal auto-assigned) |

### 2.4 Operator Configuration

| Env Var | Required | Description |
| :--- | :--- | :--- |
| `MOCK_API_KEYS` | yes for multi-tenant testing | Comma-separated `tenant_id:sk-xxx` entries. Default: `tenant_demo:sk-dev-demo`. |

Entries that lack the `sk-` prefix or the `tenant:key` shape are silently dropped — typos in env should not crash the mock.

## 3. Versioning

Versions travel in the URL (`/v1`) **and** in the `Accept-Version` header.

* Default when `Accept-Version` is absent: `v1`.
* Unknown or already-sunset versions return `406 UNSUPPORTED_VERSION`.
* Deprecated routes advertise sunset via the `Sunset: <RFC 7231 date>` and `Deprecation: true` response headers and remain functional for **12 months** after first announcement.

## 4. Environments

| Environment | Base URL | Notes |
| :--- | :--- | :--- |
| Production | `https://api.clinic.example/v1` | Real patient data. |
| Sandbox | `https://sandbox.api.clinic.example/v1` | Synthetic data; identical contract. |
| Harness (admin only) | `https://{api,sandbox}.clinic.example/_harness/*` | Requires `harness:admin`; not subject to per-tenant rate limits; **never expose to end users**. |

## 5. Pagination

(same as before — cursor-based with `cursor` + `limit` 1..100)

## 6. Rate Limiting

**Not implemented in the current mock.** No request ever returns `429`, no `X-RateLimit-*` header is emitted, and no rate-limit middleware exists. This section reserves the contract: when implementation lands it will emit `X-RateLimit-{Limit,Remaining,Reset}` on every response and `Retry-After` on `429`. The `RateLimited` response component in `openapi.yaml` is documented-but-unused for the same reason.

## 7. Errors

### 7.1 Envelope

(same envelope as before)

### 7.2 Error Code Catalog

| HTTP | Code | Meaning | Typical When |
| :---: | :--- | :--- | :--- |
| 400 | `VALIDATION_ERROR` | Request failed schema/format validation. | `details[]` names offending fields. |
| 400 | `INVALID_ESCALATION_TARGET` | Escalate called without `staff_id` or `queue`. | `POST /calls/{id}/escalate`. |
| 401 | `UNAUTHORIZED` | Missing, malformed, or unknown bearer token. | Carries `WWW-Authenticate: Bearer realm="clinic-mock"`. |
| 403 | `FORBIDDEN` | Defined for the future case of per-scope grants; **unreachable in the current mock** (every valid key passes every scope guard). | Carries `WWW-Authenticate: Bearer error="insufficient_scope", scope="<scope>"` when eventually wired. |
| 404 | `NOT_FOUND` | Resource does not exist or is not visible to the caller. | |
| 406 | `UNSUPPORTED_VERSION` | `Accept-Version` unknown or past sunset. | |
| 409 | `SLOT_TAKEN` | The referenced `slot_id` is already reserved. | `POST /appointments`. |
| 409 | `RESCHEDULE_SLOT_TAKEN` | The `new_slot_id` is already reserved. | `POST /appointments/{id}/reschedule`. |
| 409 | `INVALID_STATE_TRANSITION` | Action not allowed from the current appointment status. | Lifecycle endpoints on terminal or incompatible states. |
| 409 | `CALL_ALREADY_ENDED` | Write attempted against a terminal-state `Call`. | `PATCH /calls/{id}` and any `POST /calls/{id}/...` against `ESCALATED` or `ENDED_*`. |
| 422 | `IDEMPOTENCY_CONFLICT` | Same `Idempotency-Key` reused with a different payload. | See [Idempotency](#8-idempotency). |
| 429 | `RATE_LIMITED` | Reserved for future per-tenant rate limiting; **not currently returned** by the mock. | When implemented, will carry `Retry-After` and `X-RateLimit-*` headers. |
| 500 | `INTERNAL_ERROR` | Unexpected server failure. | Safe to retry with exponential backoff and jitter. |
| 503 | `SERVICE_UNAVAILABLE` | Temporary outage; safe to retry. | Carries `Retry-After`. |

### 7.3 Validation Rules

| Field | Rule |
| :--- | :--- |
| `phone`, `Patient.phone`, `from_number`, `to_number` | VN local 10-digit, mobile or landline: `` `^(02\|03\|05\|07\|08\|09)\d{8}$` `` |
| `from`, `to` | RFC 3339 UTC (`...Z`). `to > from`. |
| `from`/`to` window | ≤ 14 days. |
| `date` | `YYYY-MM-DD`. |
| `slot_id`, `patient_id`, `appointment_id`, `clinic_id`, `provider_id` | Opaque: `^[a-z]+_[A-Za-z0-9]+$` (prefix per resource). |
| `call_id`, `staff_id` | Opaque: `^[a-z]+_[A-Za-z0-9]+$`. |
| `notes` | ≤ 500 chars, UTF-8. |
| `reason_code` (cancel) | One of `PATIENT_NO_SHOW`, `PROVIDER_REQUEST`, `CLINIC_REBOOK`, `OTHER`. |
| `reason_code` (transfer) | One of `EQUIPMENT_FAILURE`, `PROVIDER_UNAVAILABLE`, `PATIENT_REQUEST`, `OTHER`. |
| `reason_code` (escalate) | One of `TWO_FAILED_UNDERSTANDINGS`, `OFF_SCRIPT`, `PATIENT_REQUEST`, `OTHER`. |
| `kind` (attempt) | One of `RINGOUT`, `VOICEMAIL`, `SILENT_TURN`. |
| `outcome` (end) | One of `COMPLETED`, `NO_ANSWER`, `VOICEMAIL`, `FAILED`. |
| `target_clinic_id` (transfer) | Must differ from the current `clinic_id`. |
| `Idempotency-Key` | ≤ 255 chars. |

## 8. Idempotency

(same as before — 24h window, hash-based replay)

## 9. Data Models

### `Patient`

```json
{ "id": "p_12345", "first_name": "Jane", "last_name": "Doe", "phone": "+15551234567", "dob": "1985-04-12" }
```

### `Slot`

```json
{ "slot_id": "s_987", "clinic_id": "c_001", "start_time": "2026-09-15T09:00:00Z", "end_time": "2026-09-15T09:30:00Z", "provider_id": "pr_456" }
```

### `SlotRef`

```json
{ "start_time": "2026-09-15T09:00:00Z", "end_time": "2026-09-15T09:30:00Z", "clinic_id": "c_001" }
```

### `PatientRef`

```json
{ "id": "p_12345", "name": "Jane Doe", "phone": "+15551234567" }
```

### `Appointment`

```json
{ "id": "a_555", "status": "CONFIRMED", "slot": { "...": "SlotRef" }, "patient": { "...": "PatientRef" } }
```

`status` is one of: `PENDING`, `BOOKED`, `CONFIRMED`, `CANCELLED`, `TRANSFERRED`, `RESCHEDULED`, `COMPLETED`, `NO_SHOW`.

### `Call`

```json
{
  "id": "call_01HZ...",
  "tenant_id": "tenant_123",
  "from_number": "+15551234567",
  "to_number": "+15559876543",
  "started_at": "2026-09-15T09:00:00Z",
  "ended_at": null,
  "status": "IN_PROGRESS",
  "patient_id": "p_12345",
  "verified": true,
  "attempts": [ /* CallAttempt */ ],
  "escalations": [ /* Escalation */ ],
  "linked_appointment_ids": ["a_555"]
}
```

`Call.status` is one of:
* `RINGING` — call created, not yet picked up by an agent.
* `IN_PROGRESS` — agent is handling the call.
* `ESCALATED` — transferred to staff; terminal.
* `ENDED_NO_ANSWER` — call ended because nobody picked up; terminal.
* `ENDED_VOICEMAIL` — call ended on voicemail; terminal.
* `ENDED_COMPLETED` — call ended normally; terminal.
* `ENDED_FAILED` — call ended due to error; terminal.

### `CallAttempt`

```json
{ "kind": "RINGOUT", "at": "2026-09-15T09:00:30Z", "detail": null }
```

`kind` is one of: `RINGOUT` (ring out, no answer), `VOICEMAIL` (voicemail detected), `SILENT_TURN` (agent heard no speech on a turn — e.g. the three-silent-turns scenario).

### `Escalation`

```json
{ "staff_id": "staff_42", "queue": null, "reason": "TWO_FAILED_UNDERSTANDINGS", "at": "2026-09-15T09:03:11Z" }
```

`reason` is one of: `TWO_FAILED_UNDERSTANDINGS`, `OFF_SCRIPT`, `PATIENT_REQUEST`, `OTHER`.

## 10. Appointment Lifecycle

(same diagram + matrix as before)

## 11. Reason Code Enums

### Cancel — `reason_code`

| Code | When |
| :--- | :--- |
| `PATIENT_NO_SHOW` | Patient did not arrive for the scheduled slot. |
| `PROVIDER_REQUEST` | Provider-initiated cancellation. |
| `CLINIC_REBOOK` | Clinic rebooked the slot internally. |
| `OTHER` | Anything else; supply a human-readable `notes` field. |

### Transfer — `reason_code`

| Code | When |
| :--- | :--- |
| `EQUIPMENT_FAILURE` | Equipment unavailable at the origin clinic. |
| `PROVIDER_UNAVAILABLE` | Provider reassigned. |
| `PATIENT_REQUEST` | Patient asked to be moved. |
| `OTHER` | Anything else. |

## 12. Endpoints

### Discovery & Lookup

#### `GET /patients`
Finds patient records associated with an inbound caller.
* **Scope:** `patients:read`
* **Query:** `phone` (string, required, E.164).
* **Response `200 OK`:** Paginated envelope of `Patient` (§9).

#### `GET /slots`
Retrieves genuinely open, bookable time slots. This is the **only** legal source for presenting availability to an inbound caller.
* **Scope:** `slots:read`
* **Query:** `clinic_id` (required), `from` (RFC 3339, required), `to` (RFC 3339, required, `to > from`, `to - from ≤ 14d`).
* **Response `200 OK`:** Paginated envelope of `Slot` (§9).

### Booking & Reading

#### `POST /appointments`
Creates one appointment, consuming an open slot.
* **Scope:** `appointments:write`
* **Idempotency:** Recommended — see [§8](#8-idempotency).
* **Request body:**
    ```json
    { "patient_id": "p_12345", "slot_id": "s_987", "notes": "Patient reports mild fever." }
    ```
* **Response `201 Created`:** `Appointment` with `status = PENDING` (or `BOOKED`).
* **Errors:** `400 VALIDATION_ERROR`, `404 NOT_FOUND` (patient or slot), `409 SLOT_TAKEN`, `422 IDEMPOTENCY_CONFLICT`, `429 RATE_LIMITED`.

#### `GET /appointments/{id}`
Reads a single appointment.
* **Scope:** `appointments:read`
* **Response `200 OK`:** `Appointment`.
* **Errors:** `404 NOT_FOUND`.

#### `GET /appointments`
Generates the day's call list for a specific clinic, ordered by `slot.start_time`.
* **Scope:** `appointments:read`
* **Query:** `date` (`YYYY-MM-DD`, required), `clinic_id` (required), `cursor`, `limit`.
* **Response `200 OK`:** Paginated envelope of `Appointment`.

### Lifecycle

#### `POST /appointments/{id}/confirm`
Sets status to `CONFIRMED`. **Errors:** `409 INVALID_STATE_TRANSITION`.

#### `POST /appointments/{id}/cancel`
Sets status to `CANCELLED`; logs `reason_code`.
* **Body:** `{ "reason_code": "PATIENT_NO_SHOW", "notes"?: "..." }`
* **Errors:** `400 VALIDATION_ERROR`, `409 INVALID_STATE_TRANSITION`.

#### `POST /appointments/{id}/transfer`
Sets origin appointment to `TRANSFERRED`; creates a new appointment at `target_clinic_id`.
* **Body:** `{ "target_clinic_id": "c_002", "reason_code": "EQUIPMENT_FAILURE" }`
* **Errors:** `400 VALIDATION_ERROR`, `409 INVALID_STATE_TRANSITION`.

#### `POST /appointments/{id}/reschedule`
Atomically books `new_slot_id` and releases the old one. **Errors:** `400 VALIDATION_ERROR`, `409 RESCHEDULE_SLOT_TAKEN`, `409 INVALID_STATE_TRANSITION`.

### Voice Calls

The Calls API surfaces the voice-agent's call-mechanics contract. It is the API used to record identity verification, log no-answer attempts, and escalate to staff — distinct from the Appointment API which manages booking data.

#### `POST /calls`
Starts a new inbound call.
* **Scope:** `calls:write`
* **Request body:**
    ```json
    { "from_number": "+15551234567", "to_number": "+15559876543" }
    ```
* **Response `201 Created`:** `Call` object with `status = RINGING`.
* **Webhooks:** `call.started`.

#### `GET /calls/{id}`
Reads current call state including attempts, escalations, and any appointments linked to the same verified patient.
* **Scope:** `calls:read`
* **Response `200 OK`:** `Call`.
* **Errors:** `404 NOT_FOUND`.

#### `PATCH /calls/{id}`
Updates mid-call state. Typical use: after `GET /patients` returns a match, the agent sets `verified=true` and `patient_id`.
* **Scope:** `calls:write`
* **Request body:** any subset of `{ "verified", "patient_id", "status" }`.
* **Response `200 OK`:** Updated `Call`.
* **Errors:** `400 VALIDATION_ERROR`, `404 NOT_FOUND`, `409 CALL_ALREADY_ENDED`.

#### `POST /calls/{id}/escalate`
Transfers the live call to staff. This is the **transfer-to-staff** scenario: invoked when the agent goes off-script, after two consecutive failed understandings, on patient request, or for any other reason.
* **Scope:** `calls:write`
* **Request body:**
    ```json
    { "staff_id": "staff_42", "queue"?: "triage", "reason": "TWO_FAILED_UNDERSTANDINGS" }
    ```
    At least one of `staff_id` or `queue` is required.
* **Response `200 OK`:** Updated `Call` with `status = ESCALATED` and a new `Escalation` appended.
* **Webhooks:** `call.escalated`.
* **Errors:** `400 INVALID_ESCALATION_TARGET` (neither `staff_id` nor `queue`), `400 VALIDATION_ERROR` (unknown `reason`), `404 NOT_FOUND`, `409 CALL_ALREADY_ENDED`.

#### `POST /calls/{id}/attempts`
Logs a no-answer event. The test scenarios distinguish ringing-out, voicemail, and three silent turns; the `kind` enum captures all three.
* **Scope:** `calls:write`
* **Request body:**
    ```json
    { "kind": "RINGOUT", "detail"?: "No pickup after 30s." }
    ```
* **Response `201 Created`:** Created `CallAttempt` entry; `Call.attempts` is appended to.
* **Webhooks:** `call.no_answer` (only when this attempt drives the call into a terminal `ENDED_NO_ANSWER` or `ENDED_VOICEMAIL` state).
* **Errors:** `400 VALIDATION_ERROR`, `404 NOT_FOUND`, `409 CALL_ALREADY_ENDED`.

#### `POST /calls/{id}/end`
Ends the call.
* **Scope:** `calls:write`
* **Request body:**
    ```json
    { "outcome": "COMPLETED", "reason"?: "..." }
    ```
* **Response `200 OK`:** Updated `Call` with terminal status (`ENDED_COMPLETED`, `ENDED_NO_ANSWER`, `ENDED_VOICEMAIL`, or `ENDED_FAILED`).
* **Webhooks:** `call.ended`.
* **Errors:** `400 VALIDATION_ERROR` (unknown `outcome`), `404 NOT_FOUND`, `409 CALL_ALREADY_ENDED`.

#### Call Lifecycle

`CALL_ALREADY_ENDED` is returned for any write against a call already in `ESCALATED` or `ENDED_*`. `RINGING` may transition to `IN_PROGRESS` via `PATCH`, or directly to a terminal state via `POST /calls/{id}/end`.

| From \ Action | `PATCH` (`status`) | escalate | attempts | end |
| :--- | :---: | :---: | :---: | :---: |
| `RINGING` | ✓ → `IN_PROGRESS` | ✓ | ✓ | ✓ |
| `IN_PROGRESS` | ✓ | ✓ | ✓ | ✓ |
| `ESCALATED` | ✗ (`409 CALL_ALREADY_ENDED`) | ✗ | ✗ | ✗ |
| `ENDED_NO_ANSWER` | ✗ | ✗ | ✗ | ✗ |
| `ENDED_VOICEMAIL` | ✗ | ✗ | ✗ | ✗ |
| `ENDED_COMPLETED` | ✗ | ✗ | ✗ | ✗ |
| `ENDED_FAILED` | ✗ | ✗ | ✗ | ✗ |

### Admin & Operations

Endpoints for admins and automated test suites. **Never expose to end users.** Required scope: `harness:admin`. Not subject to per-tenant rate limits.

**State inspection (read-only):**

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/_harness/state` | Full snapshot: patients, slots, appointments, calls, escalations. |
| `GET` | `/_harness/patients` | Filtered list of seeded patients. |
| `GET` | `/_harness/slots` | Filtered list of slots (with optional `clinic_id`, `from`, `to`). |
| `GET` | `/_harness/appointments` | Filtered list (with optional `clinic_id`, `date`, `status`). |
| `GET` | `/_harness/calls` | Filtered list of calls (with optional `status`, `tenant_id`). |
| `GET` | `/_harness/calls/{id}` | Single call with `attempts`, `escalations`, and `linked_appointment_ids`. |
| `GET` | `/_harness/escalations` | All escalations across all calls, ordered by `at` desc. |

**Snapshots (test isolation):**

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/_harness/snapshot` | Captures current state and returns a `snapshot_id`. |
| `POST` | `/_harness/snapshot/{id}/restore` | Resets the mock to a prior snapshot without re-seeding. |

**State mutation:**

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `POST` | `/_harness/seed` | Populates the database with mock clinics, providers, and open slots. Optional body overrides the fixture. |
| `POST` | `/_harness/reset` | Flushes the database back to a zero state. |
| `POST` | `/_harness/time-travel` | Simulates moving the system clock forward (useful for testing no-show logic). |

## 13. Webhooks

**Not implemented in the current mock.** The event shapes below are pinned here for the future emitter; no webhook is actually delivered today (no client, no delivery worker, no retries). The `webhooks:` block in `openapi.yaml` is declared-but-unused for the same reason.

When the emitter lands: the platform pushes lifecycle events to a tenant-configured HTTPS URL. Delivery is **at-least-once** with exponential backoff (1s, 5s, 30s, 5m, 30m, 2h, 12h, 24h — 8 attempts).

### 13.1 Headers on Every Delivery

| Header | Description |
| :--- | :--- |
| `X-Clinic-Event` | Event name (e.g. `appointment.confirmed`). |
| `X-Clinic-Signature` | HMAC-SHA256 of the raw body keyed by the webhook secret; format `v1=<hex>`. |
| `X-Clinic-Delivery-Id` | UUID; unique per attempt. |
| `X-Clinic-Timestamp` | Unix timestamp of the send. |

### 13.2 Event Catalog

| Event | Fires after |
| :--- | :--- |
| `appointment.created` | `POST /appointments` |
| `appointment.confirmed` | `POST /appointments/{id}/confirm` |
| `appointment.cancelled` | `POST /appointments/{id}/cancel` |
| `appointment.transferred` | `POST /appointments/{id}/transfer` |
| `appointment.rescheduled` | `POST /appointments/{id}/reschedule` |
| `call.started` | `POST /calls` |
| `call.escalated` | `POST /calls/{id}/escalate` |
| `call.no_answer` | `POST /calls/{id}/attempts` when the attempt drives the call into `ENDED_NO_ANSWER` or `ENDED_VOICEMAIL` |
| `call.ended` | `POST /calls/{id}/end` |

Each event body is the canonical resource plus a top-level `event` field:

```json
{
  "event": {
    "name": "appointment.confirmed",
    "id": "evt_01HZ...",
    "occurred_at": "2026-09-15T09:05:22Z",
    "tenant_id": "tenant_123"
  },
  "appointment": { "...": "Appointment" }
}
```

For `call.*` events, `appointment` is replaced with the `Call` object.

Consumers must respond `2xx` within **5 seconds**; otherwise the delivery is retried.

## 14. Observability — Langfuse Traces

The mock emits OpenTelemetry-compatible traces to Langfuse for every incoming API call. Tests read traces directly from Langfuse (`langfuse-cli`, the Langfuse SDK, or the Langfuse HTTP API); the mock does **not** expose a trace-polling endpoint.

### 14.1 Configuration

| Env Var | Required | Description |
| :--- | :--- | :--- |
| `LANGFUSE_PUBLIC_KEY` | yes (when traces enabled) | Project public key. |
| `LANGFUSE_SECRET_KEY` | yes (when traces enabled) | Project secret key. |
| `LANGFUSE_HOST` | yes (when traces enabled) | Langfuse host (e.g. `https://cloud.langfuse.com`, `https://us.cloud.langfuse.com`, or self-hosted). |
| `LANGFUSE_ENVIRONMENT` | optional | Tag on every trace; default `sandbox`. Use to isolate concurrent test runs. |
| `LANGFUSE_TRACES_ENABLED` | optional | `true` / `false`; default `true`. Set `false` to fully suppress trace emission (offline tests). |

When `LANGFUSE_TRACES_ENABLED=false`, traces are dropped — not buffered on the mock. Tests that need tracing keep it enabled.

### 14.2 Trace Shape

**Resource attributes (every trace):**

| Attribute | Value |
| :--- | :--- |
| `service.name` | `clinic-mock` |
| `service.version` | from `pyproject.toml` |
| `deployment.environment` | `LANGFUSE_ENVIRONMENT` (default `sandbox`) |

**Span per incoming API call,** named `http.server.request`:

| Attribute | Source |
| :--- | :--- |
| `http.request.method` | HTTP method |
| `url.path` | Path with template variables (e.g. `/v1/appointments/{id}`) |
| `url.template` | OTel URL template |
| `http.route` | Resolved route pattern |
| `http.response.status_code` | Response status |
| `server.latency_ms` | Measured on the server |
| `langfuse.tenant.id` | Resolved from API key |
| `langfuse.request.id` | Matches `X-Request-Id` (correlation key) |
| `langfuse.api_key.last4` | Last four of the bearer key (sanitized) |

**Semantic span events** are emitted on lifecycle mutations:

| Span event | Fires on |
| :--- | :--- |
| `appointment.booked` | `POST /appointments` (success) |
| `appointment.cancelled` | `POST /appointments/{id}/cancel` (success) |
| `appointment.transferred` | `POST /appointments/{id}/transfer` (success) |
| `appointment.rescheduled` | `POST /appointments/{id}/reschedule` (success) |
| `call.started` | `POST /calls` (success) |
| `call.escalated` | `POST /calls/{id}/escalate` (success) |
| `call.no_answer` | `POST /calls/{id}/attempts` that drives the call to a terminal no-answer state |
| `call.ended` | `POST /calls/{id}/end` (any `outcome`) |

Each event carries the affected resource id (`appointment_id` / `call_id`) so tests can pivot from a trace to the matching entry in `/_harness/state`.

### 14.3 Redaction (always on)

These fields are **never** written into traces or span events:

* `phone`, `Patient.phone`, `from_number`, `to_number`
* `dob`
* `notes`
* `Authorization` request header

Instead, the span emits a `request.body.redacted` event with a JSON-pointer list of redacted paths and a stable count. Span events that would contain these fields substitute the resource id only.

### 14.4 Reading Traces from Tests

Use `langfuse-cli` (no install — `npx langfuse-cli`) or the Langfuse SDK, filtered by:

* Tag `service:clinic-mock` (auto-set from `service.name`).
* `deployment.environment=<LANGFUSE_ENVIRONMENT>` to isolate runs.
* Attribute `langfuse.request.id=<X-Request-Id>` for **deterministic per-request correlation** — given any request id, the matching trace is unique.

```bash
npx langfuse-cli api traces list \
  --tag service:clinic-mock \
  --filter 'metadata.deployment.environment=ci-run-42' \
  --filter 'attributes."langfuse.request.id"=req_01HZ...'
```

The test then pivots from a span event (e.g. `call.escalated` with `call_id=call_01HZ...`) to `GET /_harness/calls/{id}` to assert mock state. Tracing is for *what happened*; mock state is for *what is now true*.

## 15. Support

| Resource | URL |
| :--- | :--- |
| Status page | `https://status.clinic.example` |
| Support email | `api-support@clinic.example` |
| OpenAPI document | [`openapi.yaml`](openapi.yaml) |
| Changelog | [`CHANGELOG.md`](CHANGELOG.md) |
