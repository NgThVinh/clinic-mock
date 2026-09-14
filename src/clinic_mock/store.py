"""In-memory store with snapshot/restore for test isolation.

Single global `db` instance; snapshot copies are deep via model_dump.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from clinic_mock.schemas import Appointment, Call, Patient, Slot


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Store:
    def __init__(self) -> None:
        self.patients: dict[str, Patient] = {}
        self.slots: dict[str, Slot] = {}
        self.appointments: dict[str, Appointment] = {}
        self.calls: dict[str, Call] = {}
        self.snapshots: dict[str, dict] = {}
        self.system_clock_offset_sec: int = 0

    def now(self) -> datetime:
        return datetime.now(timezone.utc).fromtimestamp(
            datetime.now(timezone.utc).timestamp() + self.system_clock_offset_sec,
            tz=timezone.utc,
        )

    def new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def reset(self) -> None:
        self.__init__()

    def snapshot(self) -> str:
        sid = self.new_id("snap")
        self.snapshots[sid] = {
            "patients": {k: v.model_dump() for k, v in self.patients.items()},
            "slots": {k: v.model_dump() for k, v in self.slots.items()},
            "appointments": {k: v.model_dump() for k, v in self.appointments.items()},
            "calls": {k: v.model_dump() for k, v in self.calls.items()},
            "system_clock_offset_sec": self.system_clock_offset_sec,
        }
        return sid

    def restore(self, sid: str) -> None:
        snap = self.snapshots.get(sid)
        if snap is None:
            from clinic_mock.errors import not_found

            raise not_found(f"snapshot {sid}")
        self.patients = {k: Patient(**v) for k, v in snap["patients"].items()}
        self.slots = {k: Slot(**v) for k, v in snap["slots"].items()}
        self.appointments = {k: Appointment(**v) for k, v in snap["appointments"].items()}
        self.calls = {k: Call(**v) for k, v in snap["calls"].items()}
        self.system_clock_offset_sec = snap["system_clock_offset_sec"]

    def dump(self) -> dict:
        return {
            "patients": [p.model_dump() for p in self.patients.values()],
            "slots": [s.model_dump() for s in self.slots.values()],
            "appointments": [a.model_dump() for a in self.appointments.values()],
            "calls": [c.model_dump() for c in self.calls.values()],
        }


db = Store()


# ----- seed fixtures -----

DEFAULT_SEED = {
    "clinics": [
        {"id": "c_001", "name": "Downtown Clinic"},
        {"id": "c_002", "name": "Uptown Clinic"},
    ],
    "providers": [
        {"id": "pr_456", "name": "Dr. Smith", "clinic_id": "c_001"},
        {"id": "pr_789", "name": "Dr. Lee", "clinic_id": "c_002"},
    ],
    "patients": [
        {"id": "p_12345", "first_name": "Jane", "last_name": "Doe", "phone": "+15551234567", "dob": "1985-04-12"},
        {"id": "p_67890", "first_name": "John", "last_name": "Roe", "phone": "+15559876543", "dob": "1972-11-03"},
    ],
    "slots": [
        {"slot_id": "s_987", "clinic_id": "c_001", "start_time": "2026-09-15T09:00:00Z", "end_time": "2026-09-15T09:30:00Z", "provider_id": "pr_456"},
        {"slot_id": "s_988", "clinic_id": "c_001", "start_time": "2026-09-15T09:30:00Z", "end_time": "2026-09-15T10:00:00Z", "provider_id": "pr_456"},
        {"slot_id": "s_1024", "clinic_id": "c_002", "start_time": "2026-09-15T11:00:00Z", "end_time": "2026-09-15T11:30:00Z", "provider_id": "pr_789"},
    ],
}


def seed_default() -> None:
    """Populate db with the canonical mock fixtures (idempotent: reset first)."""
    db.reset()
    db.system_clock_offset_sec = 0  # explicit reset for harness/time-travel
    for p in DEFAULT_SEED["patients"]:
        db.patients[p["id"]] = Patient(**p)
    for s in DEFAULT_SEED["slots"]:
        db.slots[s["slot_id"]] = Slot(**s)
