"""Appointment + Call state-machine helpers."""

from __future__ import annotations

from clinic_mock.errors import conflict
from clinic_mock.schemas import AppointmentStatus, CallStatus

APPOINTMENT_TRANSITIONS = {
    "confirm": {"PENDING", "BOOKED"},
    "cancel": {"PENDING", "BOOKED", "CONFIRMED"},
    "transfer": {"PENDING", "BOOKED", "CONFIRMED"},
    "reschedule": {"PENDING", "BOOKED", "CONFIRMED"},
}

CALL_TERMINAL = {"ESCALATED", "ENDED_NO_ANSWER", "ENDED_VOICEMAIL", "ENDED_COMPLETED", "ENDED_FAILED"}
CALL_TRANSITIONS = {
    "patch": {"RINGING", "IN_PROGRESS"},
    "escalate": {"RINGING", "IN_PROGRESS"},
    "attempts": {"RINGING", "IN_PROGRESS"},
    "end": {"RINGING", "IN_PROGRESS"},
}


def assert_appointment_transition(current: AppointmentStatus, action: str) -> None:
    allowed = APPOINTMENT_TRANSITIONS[action]
    if current not in allowed:
        raise conflict(
            "INVALID_STATE_TRANSITION",
            f"Cannot {action} an appointment in status {current}.",
        )


def assert_call_writable(current: CallStatus, action: str) -> None:
    if current in CALL_TERMINAL:
        raise conflict(
            "CALL_ALREADY_ENDED",
            f"Cannot {action} a call in terminal status {current}.",
        )
    if action != "patch" and current not in CALL_TRANSITIONS[action]:
        raise conflict(
            "INVALID_STATE_TRANSITION",
            f"Cannot {action} a call in status {current}.",
        )


OUTCOME_TO_CALL_STATUS = {
    "COMPLETED": "ENDED_COMPLETED",
    "NO_ANSWER": "ENDED_NO_ANSWER",
    "VOICEMAIL": "ENDED_VOICEMAIL",
    "FAILED": "ENDED_FAILED",
}


# attempt → terminal outcome hint (does not auto-end the call)
ATTEMPT_KIND_TO_OUTCOME = {
    "RINGOUT": "NO_ANSWER",
    "VOICEMAIL": "VOICEMAIL",
    # SILENT_TURN does not by itself imply end-of-call; the agent decides.
}
