"""Tests for /_harness/* admin endpoints (§4).

Per-tenant scoped. Requires auth. Used by the scoring harness only.
"""

from tests.conftest import AUTH_A, AUTH_B, write_headers


class TestHarnessState:
    def test_get_state(self, client):
        r = client.get("/_harness/state", headers=AUTH_A)
        assert r.status_code == 200
        body = r.json()
        assert "patients" in body
        assert "slots" in body
        assert "appointments" in body

    def test_state_requires_auth(self, client):
        r = client.get("/_harness/state")
        assert r.status_code == 401

    def test_state_is_tenant_scoped(self, client):
        state_a = client.get("/_harness/state", headers=AUTH_A).json()
        state_b = client.get("/_harness/state", headers=AUTH_B).json()
        apt_ids_a = {a["appointment_id"] for a in state_a["appointments"]}
        apt_ids_b = {a["appointment_id"] for a in state_b["appointments"]}
        non_canonical_a = {i for i in apt_ids_a if not i.startswith("apt_")}
        non_canonical_b = {i for i in apt_ids_b if not i.startswith("apt_")}
        assert not (non_canonical_a & non_canonical_b)


class TestHarnessCollections:
    def test_get_patients(self, client):
        r = client.get("/_harness/patients", headers=AUTH_A)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_slots(self, client):
        r = client.get("/_harness/slots", headers=AUTH_A)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_appointments(self, client):
        r = client.get("/_harness/appointments", headers=AUTH_A)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestHarnessSnapshot:
    def test_snapshot_and_restore(self, client):
        snap = client.get("/_harness/snapshot", headers=AUTH_A)
        assert snap.status_code == 200
        sid = snap.json()["snapshot_id"]
        client.post(
            "/v1/appointments/apt_00417/confirm",
            headers={**AUTH_A, **write_headers(3)},
        )
        appt = client.get("/v1/appointments/apt_00417", headers=AUTH_A).json()
        assert appt["status"] == "CONFIRMED"
        restore = client.post(f"/_harness/snapshot/{sid}/restore", headers=AUTH_A)
        assert restore.status_code == 200
        appt_after = client.get("/v1/appointments/apt_00417", headers=AUTH_A).json()
        assert appt_after["status"] == "SCHEDULED"

    def test_restore_unknown_snapshot(self, client):
        r = client.post("/_harness/snapshot/snap_nonexistent/restore", headers=AUTH_A)
        assert r.status_code == 404


class TestWritelogTimeFilter:
    def _seed_entries(self, client):
        # Three writes spread across ~3 distinct timestamps.
        sid = client.get("/_harness/snapshot", headers=AUTH_A).json()["snapshot_id"]
        client.post(
            "/v1/appointments/apt_00417/confirm",
            headers={**AUTH_A, **write_headers(3)},
        )
        first_at = client.get("/_harness/writelog?op=confirm", headers=AUTH_A).json()[
            "entries"
        ][0]["at"]
        client.post(
            "/v1/appointments/apt_00417/reschedule",
            headers={
                **AUTH_A,
                **write_headers(4),
                "Content-Type": "application/json",
            },
            json={"new_slot_id": "slot_91d2", "requested_by": "PATIENT"},
        )
        client.post(
            "/v1/appointments/apt_00417/cancel",
            headers={
                **AUTH_A,
                **write_headers(5),
                "Content-Type": "application/json",
            },
            json={"cancel_reason": "PATIENT_UNAVAILABLE", "confirmed": True},
        )
        return sid, first_at

    def test_writelog_filter_since(self, client):
        sid, first_at = self._seed_entries(client)
        r = client.get(f"/_harness/writelog?since={first_at}", headers=AUTH_A).json()
        ops = [e["op"] for e in r["entries"]]
        assert ops == ["confirm", "reschedule", "cancel"]

    def test_writelog_filter_until_drops_later_entries(self, client):
        sid, first_at = self._seed_entries(client)
        # `until` = first_at (inclusive). Should keep confirm, drop reschedule
        # and cancel. The brief's draft used second_at as the cutoff, which
        # was a no-op for our inclusive filter; the meaningful boundary is
        # first_at, which sits strictly before the next two writes.
        all_entries = client.get("/_harness/writelog", headers=AUTH_A).json()["entries"]
        second_at = all_entries[1]["at"]
        assert second_at > first_at, "test setup: writes must be ordered"
        until = first_at
        r = client.get(f"/_harness/writelog?until={until}", headers=AUTH_A).json()
        ops = [e["op"] for e in r["entries"]]
        assert "reschedule" not in ops
        assert "cancel" not in ops
        assert "confirm" in ops

    def test_writelog_filter_since_and_until_window(self, client):
        sid, first_at = self._seed_entries(client)
        all_entries = client.get("/_harness/writelog", headers=AUTH_A).json()["entries"]
        second_at = all_entries[1]["at"]
        # Window: from the first write up to (and including) the second.
        r = client.get(
            f"/_harness/writelog?since={first_at}&until={second_at}",
            headers=AUTH_A,
        ).json()
        ops = [e["op"] for e in r["entries"]]
        assert ops == ["confirm", "reschedule"]

    def test_writelog_no_filters_returns_all(self, client):
        self._seed_entries(client)
        r = client.get("/_harness/writelog", headers=AUTH_A).json()
        assert r["count"] == 3

    def test_writelog_bad_iso_returns_400_invalid_request(self, client):
        r = client.get("/_harness/writelog?since=not-a-date", headers=AUTH_A)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "INVALID_REQUEST"

    def test_writelog_since_greater_than_until_returns_400(self, client):
        r = client.get(
            "/_harness/writelog?since=2030-01-01T00:00:00Z&until=2020-01-01T00:00:00Z",
            headers=AUTH_A,
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "INVALID_REQUEST"


class TestHarnessSeedReset:
    def test_seed(self, client):
        r = client.post("/_harness/seed", headers=AUTH_A)
        assert r.status_code == 200
        assert r.json()["seeded"] is True

    def test_reset(self, client):
        client.post(
            "/v1/appointments/apt_00417/confirm",
            headers={**AUTH_A, **write_headers(3)},
        )
        r = client.post("/_harness/reset", headers=AUTH_A)
        assert r.status_code == 200
        assert r.json()["reset"] is True
        appt = client.get("/v1/appointments/apt_00417", headers=AUTH_A).json()
        assert appt["status"] == "SCHEDULED"
        assert appt["version"] == 3


class TestHarnessTimeTravel:
    def test_time_travel(self, client):
        r = client.post(
            "/_harness/time-travel",
            json={"seconds": 3600},
            headers=AUTH_A,
        )
        assert r.status_code == 200
        assert r.json()["offset_seconds"] == 3600

    def test_time_travel_negative(self, client):
        client.post(
            "/_harness/time-travel",
            json={"seconds": 3600},
            headers=AUTH_A,
        )
        r = client.post(
            "/_harness/time-travel",
            json={"seconds": -1800},
            headers=AUTH_A,
        )
        assert r.json()["offset_seconds"] == 1800

    def test_time_travel_requires_auth(self, client):
        r = client.post("/_harness/time-travel", json={"seconds": 100})
        assert r.status_code == 401
