"""Pydantic models — mirrors docs/APIs.md §9 data models."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


# ----- shared field types -----

Phone = Annotated[str, StringConstraints(pattern=r"^\+[1-9]\d{7,14}$")]
IsoDateTime = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")]
IsoDate = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]


# ----- patient / slot -----

class Patient(BaseModel):
    id: str
    first_name: str
    last_name: str
    phone: Phone
    dob: IsoDate


class Slot(BaseModel):
    slot_id: str
    clinic_id: str
    start_time: IsoDateTime
    end_time: IsoDateTime
    provider_id: str


class SlotRef(BaseModel):
    start_time: IsoDateTime
    end_time: IsoDateTime
    clinic_id: str


class PatientRef(BaseModel):
    id: str
    name: str
    phone: Phone


# ----- appointment -----

AppointmentStatus = Literal[
    "PENDING", "BOOKED", "CONFIRMED", "CANCELLED", "TRANSFERRED", "RESCHEDULED", "COMPLETED", "NO_SHOW"
]
CancelReason = Literal["PATIENT_NO_SHOW", "PROVIDER_REQUEST", "CLINIC_REBOOK", "OTHER"]
TransferReason = Literal["EQUIPMENT_FAILURE", "PROVIDER_UNAVAILABLE", "PATIENT_REQUEST", "OTHER"]


class Appointment(BaseModel):
    id: str
    status: AppointmentStatus
    slot: SlotRef
    patient: PatientRef


class AppointmentCreate(BaseModel):
    patient_id: str
    slot_id: str
    notes: str | None = Field(default=None, max_length=500)


class CancelRequest(BaseModel):
    reason_code: CancelReason
    notes: str | None = Field(default=None, max_length=500)


class TransferRequest(BaseModel):
    target_clinic_id: str
    reason_code: TransferReason


class RescheduleRequest(BaseModel):
    new_slot_id: str


# ----- call -----

CallStatus = Literal[
    "RINGING", "IN_PROGRESS", "ESCALATED",
    "ENDED_NO_ANSWER", "ENDED_VOICEMAIL", "ENDED_COMPLETED", "ENDED_FAILED",
]
AttemptKind = Literal["RINGOUT", "VOICEMAIL", "SILENT_TURN"]
EscalationReason = Literal["TWO_FAILED_UNDERSTANDINGS", "OFF_SCRIPT", "PATIENT_REQUEST", "OTHER"]
EndOutcome = Literal["COMPLETED", "NO_ANSWER", "VOICEMAIL", "FAILED"]


class CallAttempt(BaseModel):
    kind: AttemptKind
    at: IsoDateTime
    detail: str | None = None


class Escalation(BaseModel):
    staff_id: str | None = None
    queue: str | None = None
    reason: EscalationReason
    at: IsoDateTime


class Call(BaseModel):
    id: str
    tenant_id: str
    from_number: Phone
    to_number: Phone
    started_at: IsoDateTime
    ended_at: IsoDateTime | None = None
    status: CallStatus
    patient_id: str | None = None
    verified: bool = False
    attempts: list[CallAttempt] = []
    escalations: list[Escalation] = []
    linked_appointment_ids: list[str] = []


class CallCreate(BaseModel):
    from_number: Phone
    to_number: Phone


class CallPatch(BaseModel):
    verified: bool | None = None
    patient_id: str | None = None
    status: CallStatus | None = None


class EscalateRequest(BaseModel):
    staff_id: str | None = None
    queue: str | None = None
    reason: EscalationReason


class AttemptRequest(BaseModel):
    kind: AttemptKind
    detail: str | None = None


class EndRequest(BaseModel):
    outcome: EndOutcome
    reason: str | None = None


# ----- pagination envelope -----

class Page(BaseModel):
    data: list
    next_cursor: str | None = None
    has_more: bool = False
