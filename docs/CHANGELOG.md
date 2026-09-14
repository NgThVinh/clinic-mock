# Changelog

All notable changes to the Clinic Platform API are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/) and the API uses [semantic versioning](https://semver.org/) for breaking-change majors.

## [1.1.0] - 2026-09-14

### Added
- **Calls API** — separate lifecycle surface for voice-agent call mechanics (scenarios: identity verification mid-call, transfer-to-staff, no-answer logging, end-of-call).
  - `POST /calls`, `GET /calls/{id}`, `PATCH /calls/{id}`, `POST /calls/{id}/escalate`, `POST /calls/{id}/attempts`, `POST /calls/{id}/end`.
  - New scopes `calls:read`, `calls:write`.
  - New data models: `Call`, `CallAttempt`, `Escalation` and supporting enums (`CallStatus`, `AttemptKind`, `EscalationReason`, `EndOutcome`).
  - New webhook events: `call.started`, `call.escalated`, `call.no_answer`, `call.ended`.
- **Harness expansion** — state-check and snapshot/restore endpoints to support testing workflows; the platform is a mock for testing another service:
  - Read state: `GET /_harness/state`, `GET /_harness/patients`, `GET /_harness/slots`, `GET /_harness/appointments`, `GET /_harness/calls`, `GET /_harness/calls/{id}`, `GET /_harness/escalations`.
  - Snapshots: `GET /_harness/snapshot`, `POST /_harness/snapshot/{id}/restore`.
  - Mutation: `POST /_harness/seed`, `POST /_harness/reset`, `POST /_harness/time-travel`.
- **Langfuse observability contract** — the mock emits OpenTelemetry-compatible traces to Langfuse (`LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_ENVIRONMENT`, `LANGFUSE_TRACES_ENABLED`). Tests read traces from Langfuse directly — **no trace-polling API endpoint**.
  - Per-request span `http.server.request` carrying `langfuse.request.id` (matches `X-Request-Id`).
  - Semantic span events on lifecycle mutations (`appointment.booked`, `appointment.cancelled`, `appointment.transferred`, `appointment.rescheduled`, `call.started`, `call.escalated`, `call.no_answer`, `call.ended`).
  - Always-on redaction of `phone`, `dob`, `notes`, `Authorization`.
- New error codes: `INVALID_ESCALATION_TARGET` (400), `CALL_ALREADY_ENDED` (409).

### Notes
- No backward-incompatible changes from 1.0.0; all additions are new routes/scopes.

## [1.0.0] - 2026-09-14

### Added
- Initial public release of the Clinic Platform API (`v1`).
- Discovery endpoints: `GET /patients`, `GET /slots`.
- Booking & reading: `POST /appointments`, `GET /appointments/{id}`, `GET /appointments`.
- Lifecycle endpoints: `confirm`, `cancel`, `transfer`, `reschedule`.
- Admin endpoints: `POST /_harness/{seed,reset,time-travel}`.
- Standard error envelope (`{error: {code, message, request_id, details?}}`) and machine-readable error code catalog (`VALIDATION_ERROR`, `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `UNSUPPORTED_VERSION`, `SLOT_TAKEN`, `RESCHEDULE_SLOT_TAKEN`, `INVALID_STATE_TRANSITION`, `IDEMPOTENCY_CONFLICT`, `RATE_LIMITED`, `INTERNAL_ERROR`, `SERVICE_UNAVAILABLE`).
- Bearer-token authentication with scope-based authorization (`patients:read`, `slots:read`, `appointments:read`, `appointments:write`, `harness:admin`).
- Cursor-based pagination on list endpoints (`cursor`, `limit` 1..100, default 25).
- `Idempotency-Key` header with 24h replay window and `Idempotent-Replayed: true` response on replay.
- Per-tenant rate limiting with `X-RateLimit-*` headers and `429 RATE_LIMITED`.
- Webhooks: `appointment.{created,confirmed,cancelled,transferred,rescheduled}` with HMAC-SHA256 signing header `X-Clinic-Signature: v1=<hex>` and at-least-once delivery with exponential backoff.
- OpenAPI 3.1 companion document (`openapi.yaml`).
