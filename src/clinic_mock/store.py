"""In-memory store with snapshot/restore for test isolation.

Single global `db` instance; snapshot copies are deep via model_dump.

Canonical contract fixtures (Listing 3/4 ids: apt_00417, pt_3391, slot_91d2,
slot_77aa, cl_vinmec) are seeded once under the sentinel tenant `t_canonical`
and visible to every caller via `_visible_tenants()`. Per-tenant fixtures
keep the existing suffix trick so isolation tests still see distinct rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

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
    {"id": "pr_456", "name": "Bác sĩ Nguyễn Văn An", "clinic_id": "c_001", "department": "Nội tổng quát"},
    {"id": "pr_789", "name": "Bác sĩ Trần Thị Bình", "clinic_id": "c_002", "department": "Nhi khoa"},
    {"id": "pr_vinmec_1", "name": "Bác sĩ Phạm Thị Cúc", "clinic_id": "cl_vinmec", "department": "Tim mạch"},
    {"id": "pr_101", "name": "Bác sĩ Lê Minh Hoàng", "clinic_id": "c_001", "department": "Tai Mũi Họng"},
    {"id": "pr_102", "name": "Bác sĩ Vũ Ngọc Anh", "clinic_id": "c_001", "department": "Da liễu"},
    {"id": "pr_201", "name": "Bác sĩ Đỗ Thu Hương", "clinic_id": "c_002", "department": "Sản phụ khoa"},
    {"id": "pr_202", "name": "Bác sĩ Bùi Quang Huy", "clinic_id": "c_002", "department": "Cơ xương khớp"},
]


def provider_metadata(provider_id: str) -> dict[str, str]:
    """Return the stable display metadata associated with a provider id."""

    return next(provider for provider in PROVIDERS if provider["id"] == provider_id)

# Per-tenant fixtures — each row is replicated once per registered key, with
# the row id suffixed by a short tenant hash so the copies stay unique in the
# store while the row content is identical across callers.
PATIENT_FIXTURES = [
    {
        "id": "p_12345",
        "display_name": "Mai N.",
        "phone": "0912345678",
        "dob": "1985-04-12",
        "address": "Hai Bà Trưng, Hà Nội",
        "verify": {"full_name": "Nguyễn Thị Mai", "dob": "1985-04-12"},
    },
    {
        "id": "p_67890",
        "display_name": "Nam T.",
        "phone": "0987654321",
        "dob": "1972-11-03",
        "address": "Cầu Giấy, Hà Nội",
        "verify": {"full_name": "Trần Văn Nam", "dob": "1972-11-03"},
    },
]

PATIENT_FIXTURES.extend(
    [
        {"id": "p_sample_01", "display_name": "An L.", "phone": "0901234567", "dob": "1990-05-20", "address": "Đống Đa, Hà Nội", "verify": {"full_name": "L\u00ea V\u0103n An", "dob": "1990-05-20"}},
        {"id": "p_sample_02", "display_name": "D\u0169ng L.", "phone": "0862619836", "dob": "2005-01-30", "address": "Thanh Xuân, Hà Nội", "verify": {"full_name": "L\u00ea C\u00f4ng D\u0169ng", "dob": "2005-01-30"}},
        {"id": "p_sample_03", "display_name": "H\u00e0 P.", "phone": "0321456789", "dob": "1996-08-15", "address": "Hoàng Mai, Hà Nội", "verify": {"full_name": "Ph\u1ea1m Thu H\u00e0", "dob": "1996-08-15"}},
        {"id": "p_sample_04", "display_name": "Minh H.", "phone": "0387654321", "dob": "1988-12-09", "address": "Long Biên, Hà Nội", "verify": {"full_name": "Ho\u00e0ng Quang Minh", "dob": "1988-12-09"}},
        {"id": "p_sample_05", "display_name": "Lan V.", "phone": "0702345678", "dob": "1993-03-24", "address": "Nam Từ Liêm, Hà Nội", "verify": {"full_name": "V\u0169 Ng\u1ecdc Lan", "dob": "1993-03-24"}},
        {"id": "p_sample_06", "display_name": "H\u00f9ng \u0110.", "phone": "0793456789", "dob": "1982-07-11", "address": "Hà Đông, Hà Nội", "verify": {"full_name": "\u0110\u1eb7ng M\u1ea1nh H\u00f9ng", "dob": "1982-07-11"}},
        {"id": "p_sample_07", "display_name": "Trang B.", "phone": "0834567890", "dob": "2000-10-02", "address": "Ba Đình, Hà Nội", "verify": {"full_name": "B\u00f9i Thu Trang", "dob": "2000-10-02"}},
        {"id": "p_sample_08", "display_name": "Khoa N.", "phone": "0895678901", "dob": "1999-06-18", "address": "Tây Hồ, Hà Nội", "verify": {"full_name": "Nguy\u1ec5n Minh Khoa", "dob": "1999-06-18"}},
        {"id": "p_sample_09", "display_name": "Hương Đ.", "phone": "0336123456", "dob": "1987-02-14", "address": "Bắc Từ Liêm, Hà Nội", "verify": {"full_name": "Đỗ Lan Hương", "dob": "1987-02-14"}},
        {"id": "p_sample_10", "display_name": "Tuấn P.", "phone": "0347234567", "dob": "1991-09-21", "address": "Gia Lâm, Hà Nội", "verify": {"full_name": "Phan Anh Tuấn", "dob": "1991-09-21"}},
        {"id": "p_sample_11", "display_name": "Mai T.", "phone": "0358345678", "dob": "1984-05-08", "address": "Đông Anh, Hà Nội", "verify": {"full_name": "Trương Ngọc Mai", "dob": "1984-05-08"}},
        {"id": "p_sample_12", "display_name": "Long N.", "phone": "0369456789", "dob": "1997-11-19", "address": "Sóc Sơn, Hà Nội", "verify": {"full_name": "Ngô Hoàng Long", "dob": "1997-11-19"}},
        {"id": "p_sample_13", "display_name": "Yến H.", "phone": "0371567890", "dob": "1994-04-27", "address": "Thanh Trì, Hà Nội", "verify": {"full_name": "Hồ Hải Yến", "dob": "1994-04-27"}},
        {"id": "p_sample_14", "display_name": "Sơn D.", "phone": "0382678901", "dob": "1989-01-06", "address": "Mê Linh, Hà Nội", "verify": {"full_name": "Dương Minh Sơn", "dob": "1989-01-06"}},
        {"id": "p_sample_15", "display_name": "Thảo N.", "phone": "0393789012", "dob": "2001-07-12", "address": "Hoài Đức, Hà Nội", "verify": {"full_name": "Nguyễn Phương Thảo", "dob": "2001-07-12"}},
        {"id": "p_sample_16", "display_name": "Đức T.", "phone": "0524890123", "dob": "1986-10-30", "address": "Quốc Oai, Hà Nội", "verify": {"full_name": "Trần Minh Đức", "dob": "1986-10-30"}},
        {"id": "p_sample_17", "display_name": "Linh L.", "phone": "0565901234", "dob": "1998-12-03", "address": "Chương Mỹ, Hà Nội", "verify": {"full_name": "Lê Khánh Linh", "dob": "1998-12-03"}},
    ]
)


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
# Three slots matching the original sample schedule on every weekday from
# 17/09/2026 through 30/10/2026 (inclusive). These fixtures are recreated
# whenever the in-memory mock starts or resets.
_schedule_start = date(2026, 9, 17)
_schedule_end = date(2026, 10, 30)
_schedule_templates = (
    ("0900", "c_001", "09:00:00Z", "09:30:00Z", "pr_456"),
    ("0930", "c_001", "09:30:00Z", "10:00:00Z", "pr_456"),
    ("1000", "c_001", "10:00:00Z", "10:30:00Z", "pr_101"),
    ("1030", "c_001", "10:30:00Z", "11:00:00Z", "pr_102"),
    ("1100", "c_002", "11:00:00Z", "11:30:00Z", "pr_789"),
    ("1330", "c_002", "13:30:00Z", "14:00:00Z", "pr_201"),
    ("1400", "c_002", "14:00:00Z", "14:30:00Z", "pr_202"),
    ("1430", "c_001", "14:30:00Z", "15:00:00Z", "pr_101"),
    ("1500", "c_001", "15:00:00Z", "15:30:00Z", "pr_102"),
    ("1530", "c_002", "15:30:00Z", "16:00:00Z", "pr_789"),
)
_schedule_day = _schedule_start
while _schedule_day <= _schedule_end:
    if _schedule_day.weekday() < 5:
        day_token = _schedule_day.strftime("%Y%m%d")
        day_iso = _schedule_day.isoformat()
        SLOT_FIXTURES.extend(
            {
                "slot_id": f"s_{day_token}_{time_token}",
                "clinic_id": clinic_id,
                "start_time": f"{day_iso}T{start_time}",
                "end_time": f"{day_iso}T{end_time}",
                "provider_id": provider_id,
            }
            for time_token, clinic_id, start_time, end_time, provider_id in (
                _schedule_templates
            )
        )
    _schedule_day += timedelta(days=1)


CANONICAL_PATIENT_FIXTURES = [
    {
        "id": "pt_3391",
        "display_name": "N. V. A.",
        "phone": "0912345600",
        "dob": "1978-03-14",
        "address": "Hoàn Kiếm, Hà Nội",
        "verify": {"full_name": "Nguyễn Văn An", "dob": "1978-03-14"},
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
            address=f.get("address"),
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
            provider_name=provider_metadata(f["provider_id"])["name"],
            department=provider_metadata(f["provider_id"])["department"],
        )


def _seed_canonical_appointments() -> None:
    for f in CANONICAL_APPOINTMENT_FIXTURES:
        patient = db.patients[f["patient_id"]]
        appt = Appointment(
            appointment_id=f["appointment_id"],
            tenant_id=CANONICAL_TENANT,
            slot_id=f["slot_id"],
            provider_id=f["provider_id"],
            provider_name=provider_metadata(f["provider_id"])["name"],
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
                address=f.get("address"),
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
                provider_name=provider_metadata(f["provider_id"])["name"],
                department=provider_metadata(f["provider_id"])["department"],
            )
