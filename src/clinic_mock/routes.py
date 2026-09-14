"""All v1 + harness routes in one file.

Grouped by resource: discovery, appointments, calls, harness.
Single file keeps the mock's tiny surface easy to navigate; refactor only
when it grows past ~700 LOC.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Body, Header, Query, Request, Response, status

from clinic_mock.auth import optional_principal
from clinic_mock.errors import (
    conflict,
    not_found,
    unauthorized,
    unprocessable,
    validation_error,
)
from clinic_mock.lifecycle import (
    OUTCOME_TO_CALL_STATUS,
    assert_appointment_transition,
    assert_call_writable,
)
from clinic_mock.schemas import (
    Appointment,
    AppointmentCreate,
    AttemptRequest,
    Call,
    CallAttempt,
    CallCreate,
    CallPatch,
    CancelRequest,
    EndRequest,
    EscalateRequest,
    Escalation,
    PatientRef,
    RescheduleRequest,
    Slot,
    SlotRef,
    TransferRequest,
)
from clinic_mock.store import db, now_iso, seed_default


def _tenant(request: Request) -> str:
    """Resolve the caller's tenant id; raises 401 if auth didn't populate it.

    Centralised so every read/mutation routes through one guard. Routes then
    filter the in-memory store by this tenant id; cross-tenant ids surface as
    `404 NOT_FOUND` (never `403 FORBIDDEN`, which would leak existence).
    """
    principal = optional_principal(request)
    if principal is None:
        raise unauthorized()
    return principal.tenant_id


# ----- cursor pagination -----


def encode_cursor(payload: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    pad = "=" * (-len(cursor) % 4)
    return json.loads(base64.urlsafe_b64decode(cursor + pad).decode())


def paginate(
    items: list, cursor: str | None, limit: int
) -> tuple[list, str | None, bool]:
    limit = max(1, min(limit, 100))
    start = 0
    if cursor:
        try:
            start = int(decode_cursor(cursor).get("offset", 0))
        except Exception:  # noqa: BLE001
            start = 0
    page = items[start : start + limit]
    next_offset = start + limit
    has_more = next_offset < len(items)
    next_cursor = encode_cursor({"offset": next_offset}) if has_more else None
    return page, next_cursor, has_more


# ----- routers -----

v1 = APIRouter(prefix="/v1")
harness = APIRouter(prefix="/_harness")
health = APIRouter(tags=["Health"])


@health.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


# ===== Discovery =====


@v1.get("/patients", tags=["Discovery"])
def find_patients(
    request: Request,
    phone: Annotated[str, Query(pattern=r"^(02|03|05|07|08|09)\d{8}$")],
    cursor: str | None = None,
    limit: int = 25,
):
    tenant = _tenant(request)
    matched = [
        p.model_dump()
        for p in db.patients.values()
        if p.tenant_id == tenant and p.phone == phone
    ]
    page, next_cursor, has_more = paginate(matched, cursor, limit)
    return {"data": page, "next_cursor": next_cursor, "has_more": has_more}


@v1.get("/slots", tags=["Discovery"])
def list_slots(
    request: Request,
    clinic_id: str,
    from_: Annotated[
        str,
        Query(alias="from", pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"),
    ],
    to: Annotated[
        str, Query(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
    ],
    cursor: str | None = None,
    limit: int = 25,
):
    tenant = _tenant(request)
    if to <= from_:
        raise validation_error("'to' must be greater than 'from'.")
    f = datetime.fromisoformat(from_)
    t = datetime.fromisoformat(to)
    if (t - f) > timedelta(days=14):
        raise validation_error("'from'..'to' window must be <= 14 days.")

    def in_window(slot: Slot) -> bool:
        s = datetime.fromisoformat(slot.start_time)
        return slot.tenant_id == tenant and slot.clinic_id == clinic_id and f <= s < t

    matched = [s.model_dump() for s in db.slots.values() if in_window(s)]
    page, next_cursor, has_more = paginate(matched, cursor, limit)
    return {"data": page, "next_cursor": next_cursor, "has_more": has_more}


# ===== Appointments =====


@v1.post("/appointments", status_code=status.HTTP_201_CREATED, tags=["Appointments"])
def create_appointment(
    request: Request,
    body: AppointmentCreate,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", max_length=255)
    ] = None,
):
    tenant = _tenant(request)
    if idempotency_key:
        replay = _idempotent_check(
            idempotency_key, "POST /v1/appointments", body.model_dump()
        )
        if replay is not None:
            return Response(
                content=json.dumps(replay["body"]),
                status_code=replay["status"],
                headers={
                    "Idempotent-Replayed": "true",
                    "Content-Type": "application/json",
                },
            )

    patient = db.patients.get(body.patient_id)
    if not patient or patient.tenant_id != tenant:
        raise not_found(f"patient {body.patient_id}")
    slot = db.slots.get(body.slot_id)
    if not slot or slot.tenant_id != tenant:
        raise not_found(f"slot {body.slot_id}")
    appt = Appointment(
        id=db.new_id("a"),
        tenant_id=tenant,
        status="PENDING",
        slot=SlotRef(
            start_time=slot.start_time, end_time=slot.end_time, clinic_id=slot.clinic_id
        ),
        patient=PatientRef(
            id=patient.id,
            name=f"{patient.first_name} {patient.last_name}",
            phone=patient.phone,
        ),
    )
    db.appointments[appt.id] = appt
    db.slots.pop(slot.slot_id, None)  # consumed

    body_out = appt.model_dump()
    if idempotency_key:
        _idempotent_store(
            idempotency_key, "POST /v1/appointments", body.model_dump(), 201, body_out
        )
    return body_out


@v1.get("/appointments/{appt_id}", tags=["Appointments"])
def get_appointment(
    request: Request,
    appt_id: str,
):
    tenant = _tenant(request)
    appt = db.appointments.get(appt_id)
    if not appt or appt.tenant_id != tenant:
        raise not_found(f"appointment {appt_id}")
    return appt.model_dump()


@v1.get("/appointments", tags=["Appointments"])
def list_appointments(
    request: Request,
    date: Annotated[str, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")],
    clinic_id: str,
    cursor: str | None = None,
    limit: int = 25,
):
    tenant = _tenant(request)
    matched = [
        a.model_dump()
        for a in db.appointments.values()
        if a.tenant_id == tenant
        and a.slot.clinic_id == clinic_id
        and a.slot.start_time.startswith(date)
    ]
    matched.sort(key=lambda a: a["slot"]["start_time"])
    page, next_cursor, has_more = paginate(matched, cursor, limit)
    return {"data": page, "next_cursor": next_cursor, "has_more": has_more}


@v1.post("/appointments/{appt_id}/confirm", tags=["Appointments"])
def confirm_appointment(
    request: Request,
    appt_id: str,
):
    tenant = _tenant(request)
    appt = db.appointments.get(appt_id)
    if not appt or appt.tenant_id != tenant:
        raise not_found(f"appointment {appt_id}")
    assert_appointment_transition(appt.status, "confirm")
    updated = appt.model_copy(update={"status": "CONFIRMED"})
    db.appointments[appt_id] = updated
    return updated.model_dump()


@v1.post("/appointments/{appt_id}/cancel", tags=["Appointments"])
def cancel_appointment(
    request: Request,
    appt_id: str,
    body: CancelRequest,
):
    tenant = _tenant(request)
    appt = db.appointments.get(appt_id)
    if not appt or appt.tenant_id != tenant:
        raise not_found(f"appointment {appt_id}")
    assert_appointment_transition(appt.status, "cancel")
    updated = appt.model_copy(update={"status": "CANCELLED"})
    db.appointments[appt_id] = updated
    return updated.model_dump()


@v1.post("/appointments/{appt_id}/transfer", tags=["Appointments"])
def transfer_appointment(
    request: Request,
    appt_id: str,
    body: TransferRequest,
):
    tenant = _tenant(request)
    appt = db.appointments.get(appt_id)
    if not appt or appt.tenant_id != tenant:
        raise not_found(f"appointment {appt_id}")
    assert_appointment_transition(appt.status, "transfer")
    if body.target_clinic_id == appt.slot.clinic_id:
        raise validation_error(
            "'target_clinic_id' must differ from current 'clinic_id'."
        )
    updated = appt.model_copy(update={"status": "TRANSFERRED"})
    db.appointments[appt_id] = updated
    return updated.model_dump()


@v1.post("/appointments/{appt_id}/reschedule", tags=["Appointments"])
def reschedule_appointment(
    request: Request,
    appt_id: str,
    body: RescheduleRequest,
):
    tenant = _tenant(request)
    appt = db.appointments.get(appt_id)
    if not appt or appt.tenant_id != tenant:
        raise not_found(f"appointment {appt_id}")
    assert_appointment_transition(appt.status, "reschedule")
    new_slot = db.slots.get(body.new_slot_id)
    if not new_slot or new_slot.tenant_id != tenant:
        raise conflict(
            "RESCHEDULE_SLOT_TAKEN", f"new_slot_id {body.new_slot_id} is unavailable."
        )
    db.slots.pop(new_slot.slot_id, None)
    updated = appt.model_copy(
        update={
            "slot": SlotRef(
                start_time=new_slot.start_time,
                end_time=new_slot.end_time,
                clinic_id=new_slot.clinic_id,
            ),
        }
    )
    db.appointments[appt_id] = updated
    return updated.model_dump()


# ===== Calls =====


@v1.post("/calls", status_code=status.HTTP_201_CREATED, tags=["Calls"])
def create_call(
    request: Request,
    body: CallCreate,
):
    call = Call(
        id=db.new_id("call"),
        tenant_id=_tenant(request),
        from_number=body.from_number,
        to_number=body.to_number,
        started_at=now_iso(),
        ended_at=None,
        status="RINGING",
    )
    db.calls[call.id] = call
    return call.model_dump()


@v1.get("/calls/{call_id}", tags=["Calls"])
def get_call(
    request: Request,
    call_id: str,
):
    call = db.calls.get(call_id)
    if not call or call.tenant_id != _tenant(request):
        raise not_found(f"call {call_id}")
    return call.model_dump()


@v1.patch("/calls/{call_id}", tags=["Calls"])
def patch_call(
    request: Request,
    call_id: str,
    body: CallPatch,
):
    call = db.calls.get(call_id)
    if not call or call.tenant_id != _tenant(request):
        raise not_found(f"call {call_id}")
    assert_call_writable(call.status, "patch")
    updates: dict[str, Any] = {}
    if body.verified is not None:
        updates["verified"] = body.verified
    if body.patient_id is not None:
        updates["patient_id"] = body.patient_id
    if body.status is not None:
        updates["status"] = body.status
    updated = call.model_copy(update=updates)
    db.calls[call_id] = updated
    return updated.model_dump()


@v1.post("/calls/{call_id}/escalate", tags=["Calls"])
def escalate_call(
    request: Request,
    call_id: str,
    body: EscalateRequest,
):
    if not (body.staff_id or body.queue):
        from clinic_mock.errors import ApiError

        raise ApiError(
            400,
            "INVALID_ESCALATION_TARGET",
            "At least one of 'staff_id' or 'queue' is required.",
        )
    call = db.calls.get(call_id)
    if not call or call.tenant_id != _tenant(request):
        raise not_found(f"call {call_id}")
    assert_call_writable(call.status, "escalate")
    escalation = Escalation(
        staff_id=body.staff_id,
        queue=body.queue,
        reason=body.reason,
        at=now_iso(),
    )
    updated = call.model_copy(
        update={
            "status": "ESCALATED",
            "escalations": [*call.escalations, escalation],
            "ended_at": now_iso(),
        }
    )
    db.calls[call_id] = updated
    return updated.model_dump()


@v1.post(
    "/calls/{call_id}/attempts", status_code=status.HTTP_201_CREATED, tags=["Calls"]
)
def log_attempt(
    request: Request,
    call_id: str,
    body: AttemptRequest,
):
    call = db.calls.get(call_id)
    if not call or call.tenant_id != _tenant(request):
        raise not_found(f"call {call_id}")
    assert_call_writable(call.status, "attempts")
    attempt = CallAttempt(kind=body.kind, at=now_iso(), detail=body.detail)
    updated = call.model_copy(update={"attempts": [*call.attempts, attempt]})
    db.calls[call_id] = updated
    return attempt.model_dump()


@v1.post("/calls/{call_id}/end", tags=["Calls"])
def end_call(
    request: Request,
    call_id: str,
    body: EndRequest,
):
    call = db.calls.get(call_id)
    if not call or call.tenant_id != _tenant(request):
        raise not_found(f"call {call_id}")
    assert_call_writable(call.status, "end")
    new_status = OUTCOME_TO_CALL_STATUS[body.outcome]
    updated = call.model_copy(update={"status": new_status, "ended_at": now_iso()})
    db.calls[call_id] = updated
    return updated.model_dump()


# ===== Harness (tenant-scoped) =====


@harness.get("/state", tags=["Admin"])
def harness_state(request: Request):
    tenant = _tenant(request)
    return {
        "patients": [
            p.model_dump() for p in db.patients.values() if p.tenant_id == tenant
        ],
        "slots": [s.model_dump() for s in db.slots.values() if s.tenant_id == tenant],
        "appointments": [
            a.model_dump() for a in db.appointments.values() if a.tenant_id == tenant
        ],
        "calls": [c.model_dump() for c in db.calls.values() if c.tenant_id == tenant],
    }


@harness.get("/patients", tags=["Admin"])
def harness_patients(request: Request):
    tenant = _tenant(request)
    return [p.model_dump() for p in db.patients.values() if p.tenant_id == tenant]


@harness.get("/slots", tags=["Admin"])
def harness_slots(request: Request):
    tenant = _tenant(request)
    return [s.model_dump() for s in db.slots.values() if s.tenant_id == tenant]


@harness.get("/appointments", tags=["Admin"])
def harness_appointments(request: Request):
    tenant = _tenant(request)
    return [a.model_dump() for a in db.appointments.values() if a.tenant_id == tenant]


@harness.get("/calls", tags=["Admin"])
def harness_calls(request: Request):
    tenant = _tenant(request)
    return [c.model_dump() for c in db.calls.values() if c.tenant_id == tenant]


@harness.get("/calls/{call_id}", tags=["Admin"])
def harness_get_call(request: Request, call_id: str):
    call = db.calls.get(call_id)
    if not call or call.tenant_id != _tenant(request):
        raise not_found(f"call {call_id}")
    return call.model_dump()


@harness.get("/escalations", tags=["Admin"])
def harness_escalations(request: Request):
    tenant = _tenant(request)
    out: list[dict] = []
    for c in db.calls.values():
        if c.tenant_id != tenant:
            continue
        for e in c.escalations:
            out.append({"call_id": c.id, **e.model_dump()})
    out.sort(key=lambda e: e["at"], reverse=True)
    return out


@harness.get("/snapshot", tags=["Admin"])
def harness_snapshot(request: Request):
    sid = db.snapshot()
    return {"snapshot_id": sid}


@harness.post("/snapshot/{sid}/restore", tags=["Admin"])
def harness_snapshot_restore(request: Request, sid: str):
    db.restore(sid)
    return {"restored": sid}


@harness.post("/seed", tags=["Admin"])
def harness_seed(request: Request):
    seed_default()
    return {"seeded": True}


@harness.post("/reset", tags=["Admin"])
def harness_reset(request: Request):
    db.reset()
    return {"reset": True}


@harness.post("/time-travel", tags=["Admin"])
def harness_time_travel(request: Request, body: dict = Body(default={})):  # noqa: B008
    seconds = int(body.get("seconds", 0))
    db.system_clock_offset_sec += seconds
    return {"offset_seconds": db.system_clock_offset_sec}


# ----- Idempotency cache (in-memory, 24h) -----

_idempotency: dict[str, dict[str, Any]] = {}


def _idempotent_check(
    key: str, endpoint: str, payload: dict[str, Any]
) -> dict[str, Any] | None:
    slot = _idempotency.get(f"{endpoint}:{key}")
    if not slot:
        return None
    if slot["expires_at"] < datetime.now(UTC):
        _idempotency.pop(f"{endpoint}:{key}", None)
        return None
    if slot["payload_hash"] != hash(json.dumps(payload, sort_keys=True)):
        raise unprocessable(
            "IDEMPOTENCY_CONFLICT", "Idempotency-Key reused with a different payload."
        )
    return slot["response"]


def _idempotent_store(
    key: str,
    endpoint: str,
    payload: dict[str, Any],
    status_code: int,
    response_body: dict[str, Any],
) -> None:
    _idempotency[f"{endpoint}:{key}"] = {
        "payload_hash": hash(json.dumps(payload, sort_keys=True)),
        "response": {"status": status_code, "body": response_body},
        "expires_at": datetime.now(UTC) + timedelta(hours=24),
    }
