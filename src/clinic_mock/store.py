"""In-memory store with snapshot/restore for test isolation.

Single global `db` instance; snapshot copies are deep via model_dump.

Canonical contract fixtures (Listing 3/4 ids: apt_00417, pt_3391, slot_91d2,
slot_77aa, cl_vinmec) are seeded once under the sentinel tenant `t_canonical`
and visible to every caller via `_visible_tenants()`. Per-tenant fixtures
keep the existing suffix trick so isolation tests still see distinct rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from clinic_mock.auth import derive_tenant_id
from clinic_mock.schemas import (
    Appointment,
    Patient,
    PatientRef,
    PatientVerify,
    Slot,
)


# Tenant id under which contract canonical fixtures live. Read by the route
# helpers to widen the tenant filter — see _visible_tenants() in routes.py.
CANONICAL_TENANT = "t_canonical"


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Store:
    def __init__(self) -> None:
        self.patients: dict[str, Patient] = {}
        self.slots: dict[str, Slot] = {}
        self.appointments: dict[str, Appointment] = {}
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
        self.system_clock_offset_sec = snap["system_clock_offset_sec"]

    def dump(self) -> dict:
        return {
            "patients": [p.model_dump() for p in self.patients.values()],
            "slots": [s.model_dump() for s in self.slots.values()],
            "appointments": [a.model_dump() for a in self.appointments.values()],
        }


db = Store()


# ----- seed fixtures -----

CLINICS = [
    {"id": "c_001", "name": "Phòng khám Đa khoa Trung tâm"},
    {"id": "c_002", "name": "Phòng khám Đa khoa Cầu Giấy"},
    {"id": "cl_vinmec", "name": "Vinmec Times City"},
]

PROVIDERS = [
    {"id": "pr_456", "name": "Bác sĩ Nguyễn Văn An", "clinic_id": "c_001"},
    {"id": "pr_789", "name": "Bác sĩ Trần Thị Bình", "clinic_id": "c_002"},
    {"id": "pr_vinmec_1", "name": "Bác sĩ Phạm Thị Cúc", "clinic_id": "cl_vinmec"},
]

# Per-tenant fixtures — each row is replicated once per registered key, with
# the row id suffixed by a short tenant hash so the copies stay unique in the
# store while the row content is identical across callers.
PATIENT_FIXTURES = [
    {
        "id": "p_12345",
        "display_name": "Mai N.",
        "phone": "0912345678",
        "dob": "1985-04-12",
        "verify": {"full_name": "Nguyễn Thị Mai", "dob": "1985-04-12"},
    },
    {
        "id": "p_67890",
        "display_name": "Nam T.",
        "phone": "0987654321",
        "dob": "1972-11-03",
        "verify": {"full_name": "Trần Văn Nam", "dob": "1972-11-03"},
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

# Canonical contract fixtures — Listing 3/4. Seeded once under t_canonical
# and visible to all tenants. apt_00417 consumes slot_77aa (NOT in db.slots).
CANONICAL_PATIENT_FIXTURES = [
    {
        "id": "pt_3391",
        "display_name": "N. V. A.",
        "phone": "0912345600",
        "dob": "1978-03-14",
        "verify": {"full_name": "Nguyễn Văn A", "dob": "1978-03-14"},
    },
]

CANONICAL_SLOT_FIXTURES = [
    # Listing 4 — the open slot the bot will pick during reschedule.
    {
        "slot_id": "slot_91d2",
        "clinic_id": "cl_vinmec",
        "start_time": "2026-10-14T15:00:00+07:00",
        "end_time": "2026-10-14T15:30:00+07:00",
        "provider_id": "pr_vinmec_1",
    },
]

CANONICAL_APPOINTMENT_FIXTURES = [
    # Listing 3 — apt_00417 occupies slot_77aa (which is NOT seeded in
    # db.slots). Listing 4's reschedule flow releases slot_77aa back.
    {
        "appointment_id": "apt_00417",
        "slot_id": "slot_77aa",
        "provider_id": "pr_vinmec_1",
        "status": "SCHEDULED",
        "clinic_id": "cl_vinmec",
        "starts_at": "2026-10-14T15:30:00+07:00",
        "ends_at": "2026-10-14T16:00:00+07:00",
        "department": "Nội tổng quát",
        "patient_id": "pt_3391",
        "attempt_count": 0,
        "version": 3,
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
    """Short, stable suffix used to disambiguate per-scope fixture copies."""
    return tenant[-4:]


def _seed_canonical_patients() -> None:
    for f in CANONICAL_PATIENT_FIXTURES:
        db.patients[f["id"]] = Patient(
            patient_id=f["id"],
            tenant_id=CANONICAL_TENANT,
            display_name=f["display_name"],
            phone=f["phone"],
            dob=f["dob"],
            verify=PatientVerify(**f["verify"]),
        )


def _seed_canonical_slots() -> None:
    for f in CANONICAL_SLOT_FIXTURES:
        db.slots[f["slot_id"]] = Slot(
            slot_id=f["slot_id"],
            tenant_id=CANONICAL_TENANT,
            clinic_id=f["clinic_id"],
            start_time=f["start_time"],
            end_time=f["end_time"],
            provider_id=f["provider_id"],
        )


def _seed_canonical_appointments() -> None:
    for f in CANONICAL_APPOINTMENT_FIXTURES:
        patient = db.patients[f["patient_id"]]
        appt = Appointment(
            appointment_id=f["appointment_id"],
            tenant_id=CANONICAL_TENANT,
            slot_id=f["slot_id"],
            provider_id=f["provider_id"],
            status=f["status"],
            clinic_id=f["clinic_id"],
            starts_at=f["starts_at"],
            ends_at=f["ends_at"],
            department=f["department"],
            patient=PatientRef(
                patient_id=patient.patient_id,
                display_name=patient.display_name,
                verify=patient.verify,
            ),
            attempt_count=f["attempt_count"],
            version=f["version"],
        )
        db.appointments[f["appointment_id"]] = appt


def seed_default() -> None:
    """Populate db with the canonical mock fixtures (idempotent: reset first).

    Canonical contract fixtures seed once under `t_canonical` and are visible
    to every tenant. Per-tenant fixtures replicate per registered key with a
    short tenant hash suffix.
    """
    db.reset()
    db.system_clock_offset_sec = 0
    tenants = _seed_tenants()

    _seed_canonical_patients()
    _seed_canonical_slots()
    _seed_canonical_appointments()

    for tenant in tenants:
        suffix = _scope_suffix(tenant)
        for f in PATIENT_FIXTURES:
            pid = f"{f['id']}_{suffix}"
            db.patients[pid] = Patient(
                patient_id=pid,
                tenant_id=tenant,
                display_name=f["display_name"],
                phone=f["phone"],
                dob=f["dob"],
                verify=PatientVerify(**f["verify"]),
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
