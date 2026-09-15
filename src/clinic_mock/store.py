"""In-memory store with snapshot/restore for test isolation.

Single global `db` instance; snapshot copies are deep via model_dump.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from clinic_mock.auth import derive_tenant_id
from clinic_mock.schemas import Appointment, Call, Patient, Slot


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Store:
    def __init__(self) -> None:
        self.patients: dict[str, Patient] = {}
        self.slots: dict[str, Slot] = {}
        self.appointments: dict[str, Appointment] = {}
        self.calls: dict[str, Call] = {}
        self.snapshots: dict[str, dict] = {}
        self.system_clock_offset_sec: int = 0

    def now(self) -> datetime:
        return datetime.now(UTC).fromtimestamp(
            datetime.now(UTC).timestamp() + self.system_clock_offset_sec,
            tz=UTC,
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
        self.appointments = {
            k: Appointment(**v) for k, v in snap["appointments"].items()
        }
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

CLINICS = [
    {"id": "c_001", "name": "Phòng khám Đa khoa Trung tâm"},
    {"id": "c_002", "name": "Phòng khám Đa khoa Cầu Giấy"},
]

PROVIDERS = [
    {"id": "pr_456", "name": "Bác sĩ Nguyễn Văn An", "clinic_id": "c_001"},
    {"id": "pr_789", "name": "Bác sĩ Trần Thị Bình", "clinic_id": "c_002"},
]

# Canonical fixture rows. Each row is replicated once per registered key
# at seed time, with the row id suffixed by a short tenant hash so the
# copies stay unique in the store while the row content is identical
# across callers.
PATIENT_FIXTURES = [
    {
        "id": "p_12345",
        "first_name": "Mai",
        "last_name": "Nguyễn Thị",
        "phone": "0912345678",
        "dob": "1985-04-12",
    },
    {
        "id": "p_67890",
        "first_name": "Nam",
        "last_name": "Trần Văn",
        "phone": "0987654321",
        "dob": "1972-11-03",
    },
]

SLOT_FIXTURES = [
    {
        "slot_id": "s_987",
        "clinic_id": "c_001",
        "start_time": "2026-09-15T09:00:00Z",
        "end_time": "2026-09-15T09:30:00Z",
        "provider_id": "pr_456",
    },
    {
        "slot_id": "s_988",
        "clinic_id": "c_001",
        "start_time": "2026-09-15T09:30:00Z",
        "end_time": "2026-09-15T10:00:00Z",
        "provider_id": "pr_456",
    },
    {
        "slot_id": "s_1024",
        "clinic_id": "c_002",
        "start_time": "2026-09-15T11:00:00Z",
        "end_time": "2026-09-15T11:30:00Z",
        "provider_id": "pr_789",
    },
]


def _seed_tenants() -> list[str]:
    """Resolve the isolation scopes used by the seed fixtures.

    Parses `MOCK_API_KEYS` directly in env order — the registry is a set
    and would lose insertion order. Falls back to a single derived scope
    if the env is empty so the mock stays usable with zero env tweaks.
    """
    from clinic_mock.config import settings

    raw = settings.mock_auth.API_KEYS
    keys: list[str] = []
    for entry in raw.split(","):
        e = entry.strip()
        if not e:
            continue
        if ":" in e:
            _, e = (p.strip() for p in e.split(":", 1))
        keys.append(e)
    if not keys:
        keys = ["sk_unset"]
    tenants = [derive_tenant_id(k) for k in keys]
    seen: set[str] = set()
    unique: list[str] = []
    for t in tenants:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def _scope_suffix(tenant: str) -> str:
    """Short, stable suffix used to disambiguate per-scope fixture copies.

    The full `tenant` id is opaque and long; for fixture ids a 4-char tail
    is plenty to keep `p_12345_a3f9` and `p_12345_2c81` distinct while
    still being readable in logs.
    """
    return tenant[-4:]


def seed_default() -> None:
    """Populate db with the canonical mock fixtures (idempotent: reset first).

    Every registered key gets a full copy of every fixture row, so each
    caller sees the same mock content under their own isolation scope.
    """
    db.reset()
    db.system_clock_offset_sec = 0  # explicit reset for harness/time-travel
    tenants = _seed_tenants()

    for tenant in tenants:
        suffix = _scope_suffix(tenant)
        for f in PATIENT_FIXTURES:
            pid = f"{f['id']}_{suffix}"
            db.patients[pid] = Patient(
                id=pid,
                tenant_id=tenant,
                first_name=f["first_name"],
                last_name=f["last_name"],
                phone=f["phone"],
                dob=f["dob"],
            )
        for f in SLOT_FIXTURES:
            sid = f"{f['slot_id']}_{suffix}"
            db.slots[sid] = Slot(
                slot_id=sid,
                tenant_id=tenant,
                clinic_id=f["clinic_id"],
                start_time=f["start_time"],
                end_time=f["end_time"],
                provider_id=f["provider_id"],
            )
