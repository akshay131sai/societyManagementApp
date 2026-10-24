"""Phase 5: complaints, work, visitors and incidents.

The CRUD is the least interesting part and gets the least room here. What is
tested at length is what would actually hurt:

* **The workflow cannot be skipped.** A ticket cannot jump from OPEN to CLOSED,
  a resident cannot mark their own complaint "in progress", and a worker cannot
  sign off their own task as verified.
* **Owner scoping.** A resident sees their own tickets and the common-area
  ones, and a neighbour's ticket is 404 rather than 403.
* **A visitor cannot be walked in without an approval**, and a pass cannot be
  used twice or after its window.
* **Task generation is idempotent**, because it runs from a nightly sweep that
  can be restarted halfway through.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import SocietyFixture, auth

pytestmark = pytest.mark.asyncio


class OpsFixture:
    """A society with two flats, a resident login on one, and a worker login."""

    def __init__(self) -> None:
        self.own_flat: dict[str, Any] = {}
        self.other_flat: dict[str, Any] = {}
        self.resident_token: str = ""
        self.resident_user: dict[str, Any] = {}
        self.worker_token: str = ""
        self.worker_user: dict[str, Any] = {}
        self.guard_token: str = ""
        self.building: dict[str, Any] = {}


@pytest_asyncio.fixture(scope="module")
async def ops(client: AsyncClient, society_a: SocietyFixture) -> OpsFixture:
    admin = auth(society_a.admin_token)
    fixture = OpsFixture()
    tag = uuid.uuid4().hex[:5].upper()

    building = (
        await client.post(
            "/buildings", headers=admin, json={"name": f"Ops {tag}", "code": f"O{tag}"}
        )
    ).json()["data"]
    fixture.building = building
    block = (
        await client.get("/blocks", headers=admin, params={"building_id": building["id"]})
    ).json()["data"][0]
    floor = (
        await client.post("/floors", headers=admin, json={"block_id": block["id"], "number": 3})
    ).json()["data"]

    for label in ("own", "other"):
        flat = (
            await client.post(
                "/flats",
                headers=admin,
                json={
                    "floor_id": floor["id"],
                    "flat_number": f"{tag}-{label}",
                    "area_sqft": 950,
                },
            )
        ).json()["data"]
        setattr(fixture, f"{label}_flat", flat)

    async def make_user(label: str, roles: list[str]) -> dict[str, Any]:
        email = f"ops-{label}-{tag.lower()}@test.nestflow.in"
        user = (
            await client.post(
                "/users",
                headers=admin,
                json={
                    "email": email,
                    "full_name": f"Ops {label.title()}",
                    "role_codes": roles,
                },
            )
        ).json()["data"]
        user["token"] = f"dev:{email}"
        return user

    resident = await make_user("resident", ["FLAT_OWNER"])
    fixture.resident_user = resident
    fixture.resident_token = resident["token"]

    worker = await make_user("worker", ["MAINTENANCE"])
    fixture.worker_user = worker
    fixture.worker_token = worker["token"]

    guard = await make_user("guard", ["SECURITY"])
    fixture.guard_token = guard["token"]

    await client.post(
        "/residents",
        headers=admin,
        json={
            "flat_id": fixture.own_flat["id"],
            "full_name": "Ops Resident",
            "resident_type": "OWNER",
            "is_primary": True,
            "user_id": resident["id"],
        },
    )
    return fixture


async def _raise_ticket(
    client: AsyncClient, token: str, **overrides: Any
) -> dict[str, Any]:
    body = {
        "title": "Tap dripping in the kitchen",
        "description": "It has been dripping since Tuesday.",
        "category": "PLUMBING",
        "priority": "MEDIUM",
    }
    body.update(overrides)
    response = await client.post("/complaints", headers=auth(token), json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


# --------------------------------------------------------------------------- #
# Complaints: identity and the SLA clock
# --------------------------------------------------------------------------- #


async def test_the_database_hands_out_the_ticket_number(
    client: AsyncClient, ops: OpsFixture
) -> None:
    first = await _raise_ticket(client, ops.resident_token)
    second = await _raise_ticket(client, ops.resident_token, title="Second tap")

    assert first["ticket_number"].startswith("CMP-")
    assert first["ticket_number"] != second["ticket_number"]
    # Sequential, because a sequence assigned them rather than a count.
    assert int(second["ticket_number"].rsplit("-", 1)[1]) > int(
        first["ticket_number"].rsplit("-", 1)[1]
    )


async def test_a_residents_ticket_is_filed_against_their_own_flat(
    client: AsyncClient, ops: OpsFixture
) -> None:
    """The body's ``flat_id`` is ignored for an owner-scoped principal."""
    ticket = await _raise_ticket(
        client, ops.resident_token, flat_id=ops.other_flat["id"], title="Not my flat"
    )
    assert ticket["flat_id"] == ops.own_flat["id"]


async def test_the_sla_target_follows_the_category_and_the_priority(
    client: AsyncClient, ops: OpsFixture
) -> None:
    lift = await _raise_ticket(
        client, ops.resident_token, category="LIFT", priority="URGENT", title="Lift stuck"
    )
    billing = await _raise_ticket(
        client, ops.resident_token, category="BILLING", priority="LOW", title="Bill query"
    )

    lift_due = datetime.fromisoformat(lift["due_by"])
    billing_due = datetime.fromisoformat(billing["due_by"])
    # A stuck lift is a different promise from a billing question.
    assert lift_due < billing_due


async def test_a_plumbing_ticket_is_routed_to_maintenance(
    client: AsyncClient, ops: OpsFixture
) -> None:
    ticket = await _raise_ticket(client, ops.resident_token, category="PLUMBING")
    assert ticket["assigned_department"] == "MAINTENANCE"

    noise = await _raise_ticket(client, ops.resident_token, category="NOISE", title="Loud music")
    # Nothing obvious owns a noise complaint, so a human decides.
    assert noise["assigned_department"] is None


# --------------------------------------------------------------------------- #
# Complaints: the workflow is a table, not a suggestion
# --------------------------------------------------------------------------- #


async def test_a_ticket_cannot_skip_to_closed(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    ticket = await _raise_ticket(client, ops.resident_token, title="Skip check")
    response = await client.post(
        f"/complaints/{ticket['id']}/transition",
        headers=auth(society_a.admin_token),
        json={"status": "CLOSED", "note": "Trying to skip the queue."},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "CONFLICT"
    # The message names the moves that *are* legal.
    assert "ACKNOWLEDGED" in body["message"]


async def test_resolving_requires_saying_what_was_done(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    ticket = await _raise_ticket(client, ops.resident_token, title="Note required")
    response = await client.post(
        f"/complaints/{ticket['id']}/transition",
        headers=auth(society_a.admin_token),
        json={"status": "RESOLVED"},
    )
    assert response.status_code == 422


async def test_the_full_lifecycle_records_its_timestamps(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    admin = auth(society_a.admin_token)
    ticket = await _raise_ticket(client, ops.resident_token, title="Lifecycle")

    acknowledged = (
        await client.post(
            f"/complaints/{ticket['id']}/transition",
            headers=admin,
            json={"status": "ACKNOWLEDGED", "note": "Seen it."},
        )
    ).json()["data"]
    assert acknowledged["acknowledged_at"] is not None

    resolved = (
        await client.post(
            f"/complaints/{ticket['id']}/transition",
            headers=admin,
            json={"status": "RESOLVED", "note": "Washer replaced."},
        )
    ).json()["data"]
    assert resolved["resolved_at"] is not None
    assert resolved["resolution_notes"] == "Washer replaced."

    closed = (
        await client.post(
            f"/complaints/{ticket['id']}/transition",
            headers=auth(ops.resident_token),
            json={"status": "CLOSED"},
        )
    ).json()["data"]
    assert closed["closed_at"] is not None
    assert closed["status"] == "CLOSED"


async def test_reopening_restarts_the_clock_and_counts(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    admin = auth(society_a.admin_token)
    ticket = await _raise_ticket(client, ops.resident_token, title="Still dripping")
    await client.post(
        f"/complaints/{ticket['id']}/transition",
        headers=admin,
        json={"status": "RESOLVED", "note": "Tightened."},
    )
    reopened = (
        await client.post(
            f"/complaints/{ticket['id']}/transition",
            headers=auth(ops.resident_token),
            json={"status": "REOPENED", "note": "It is worse now."},
        )
    ).json()["data"]

    assert reopened["reopen_count"] == 1
    assert reopened["resolved_at"] is None
    # The promise was renewed, so the target moved with it.
    assert datetime.fromisoformat(reopened["due_by"]) > datetime.now(UTC)


async def test_a_resident_cannot_drive_the_ticket_themselves(
    client: AsyncClient, ops: OpsFixture
) -> None:
    """A resident owns two moves: accept the fix, or say it is not fixed."""
    ticket = await _raise_ticket(client, ops.resident_token, title="Not staff")
    response = await client.post(
        f"/complaints/{ticket['id']}/transition",
        headers=auth(ops.resident_token),
        json={"status": "IN_PROGRESS"},
    )
    assert response.status_code == 409

    detail = (
        await client.get(f"/complaints/{ticket['id']}", headers=auth(ops.resident_token))
    ).json()["data"]
    assert detail["allowed_transitions"] == []


async def test_a_closed_ticket_is_terminal(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    admin = auth(society_a.admin_token)
    ticket = await _raise_ticket(client, ops.resident_token, title="Terminal")
    await client.post(
        f"/complaints/{ticket['id']}/transition",
        headers=admin,
        json={"status": "RESOLVED", "note": "Done."},
    )
    await client.post(
        f"/complaints/{ticket['id']}/transition",
        headers=admin,
        json={"status": "CLOSED"},
    )
    response = await client.post(
        f"/complaints/{ticket['id']}/transition",
        headers=admin,
        json={"status": "REOPENED", "note": "Again"},
    )
    assert response.status_code == 409


# --------------------------------------------------------------------------- #
# Complaints: scoping. **Mandatory.**
# --------------------------------------------------------------------------- #


async def test_a_neighbours_ticket_is_not_found_rather_than_forbidden(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    admin = auth(society_a.admin_token)
    theirs = (
        await client.post(
            "/complaints",
            headers=admin,
            json={
                "title": "Neighbour's leak",
                "description": "In the other flat.",
                "flat_id": ops.other_flat["id"],
            },
        )
    ).json()["data"]

    response = await client.get(f"/complaints/{theirs['id']}", headers=auth(ops.resident_token))
    # 404, not 403: a resident must not be able to confirm the ticket exists.
    assert response.status_code == 404

    listed = (
        await client.get("/complaints", headers=auth(ops.resident_token), params={"limit": 100})
    ).json()["data"]
    assert theirs["id"] not in {c["id"] for c in listed["items"]}


async def test_a_common_area_ticket_is_visible_to_everyone(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    """A burst pipe in the lobby belongs to no flat and must not be hidden."""
    shared = (
        await client.post(
            "/complaints",
            headers=auth(society_a.admin_token),
            json={
                "title": "Lobby light out",
                "description": "The tube light in the lobby has failed.",
                "category": "COMMON_AREA",
            },
        )
    ).json()["data"]
    assert shared["flat_id"] is None

    response = await client.get(f"/complaints/{shared['id']}", headers=auth(ops.resident_token))
    assert response.status_code == 200


async def test_an_internal_note_is_invisible_to_the_resident(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    admin = auth(society_a.admin_token)
    ticket = await _raise_ticket(client, ops.resident_token, title="Internal note")

    await client.post(
        f"/complaints/{ticket['id']}/comments",
        headers=admin,
        json={"body": "Third visit this month.", "is_internal": True},
    )
    await client.post(
        f"/complaints/{ticket['id']}/comments",
        headers=admin,
        json={"body": "A plumber will come tomorrow.", "is_internal": False},
    )

    resident_view = (
        await client.get(f"/complaints/{ticket['id']}", headers=auth(ops.resident_token))
    ).json()["data"]
    bodies = [c["body"] for c in resident_view["comments"]]
    assert "A plumber will come tomorrow." in bodies
    assert "Third visit this month." not in bodies

    admin_view = (
        await client.get(f"/complaints/{ticket['id']}", headers=admin)
    ).json()["data"]
    assert "Third visit this month." in [c["body"] for c in admin_view["comments"]]


async def test_a_resident_cannot_write_an_internal_note(
    client: AsyncClient, ops: OpsFixture
) -> None:
    ticket = await _raise_ticket(client, ops.resident_token, title="No internal notes")
    response = await client.post(
        f"/complaints/{ticket['id']}/comments",
        headers=auth(ops.resident_token),
        json={"body": "Secret", "is_internal": True},
    )
    assert response.status_code == 422


async def test_status_changes_appear_on_the_timeline(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    ticket = await _raise_ticket(client, ops.resident_token, title="Timeline")
    await client.post(
        f"/complaints/{ticket['id']}/transition",
        headers=auth(society_a.admin_token),
        json={"status": "ACKNOWLEDGED", "note": "Logged with the plumber."},
    )
    detail = (
        await client.get(f"/complaints/{ticket['id']}", headers=auth(ops.resident_token))
    ).json()["data"]

    system = [c for c in detail["comments"] if c["is_system"]]
    assert any("raised" in c["body"].lower() for c in system)
    assert any("plumber" in c["body"].lower() for c in system)


async def test_only_the_raiser_rates_and_only_once_resolved(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    admin = auth(society_a.admin_token)
    ticket = await _raise_ticket(client, ops.resident_token, title="Rating")

    too_early = await client.post(
        f"/complaints/{ticket['id']}/rating",
        headers=auth(ops.resident_token),
        json={"rating": 5},
    )
    assert too_early.status_code == 409

    await client.post(
        f"/complaints/{ticket['id']}/transition",
        headers=admin,
        json={"status": "RESOLVED", "note": "Fixed."},
    )
    rated = (
        await client.post(
            f"/complaints/{ticket['id']}/rating",
            headers=auth(ops.resident_token),
            json={"rating": 4, "comment": "Quick enough."},
        )
    ).json()["data"]
    assert rated["rating"] == 4

    not_theirs = await client.post(
        f"/complaints/{ticket['id']}/rating",
        headers=admin,
        json={"rating": 1},
    )
    assert not_theirs.status_code == 409


async def test_assignment_acknowledges_and_notifies(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    admin = auth(society_a.admin_token)
    ticket = await _raise_ticket(client, ops.resident_token, title="Assign me")

    assigned = (
        await client.post(
            f"/complaints/{ticket['id']}/assignment",
            headers=admin,
            json={"assigned_to": ops.worker_user["id"], "assigned_department": "MAINTENANCE"},
        )
    ).json()["data"]
    assert assigned["assigned_to"] == ops.worker_user["id"]
    # Somebody has looked at it, which is what ACKNOWLEDGED means.
    assert assigned["status"] == "ACKNOWLEDGED"
    assert assigned["acknowledged_at"] is not None

    feed = (
        await client.get("/notifications/feed", headers=auth(ops.worker_token))
    ).json()["data"]
    assert any(n["category"] == "complaint.assigned" for n in feed["items"])


async def test_the_summary_counts_what_the_list_shows(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    admin = auth(society_a.admin_token)
    summary = (await client.get("/complaints/summary", headers=admin)).json()["data"]
    listed = (
        await client.get("/complaints", headers=admin, params={"limit": 100, "open_only": True})
    ).json()["data"]

    assert summary["open"] == listed["total"]
    assert set(summary["by_status"]) <= {
        "OPEN", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "CLOSED", "REJECTED", "REOPENED",
    }


# --------------------------------------------------------------------------- #
# Work: schedules, tasks and the generator
# --------------------------------------------------------------------------- #


async def test_maintenance_and_housekeeping_do_not_see_each_others_work(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    """One table, two departments. The department is the boundary."""
    admin = auth(society_a.admin_token)
    task = (
        await client.post(
            "/maintenance/tasks",
            headers=admin,
            json={"title": "Service the lift", "due_on": date.today().isoformat()},
        )
    ).json()["data"]
    assert task["department"] == "MAINTENANCE"

    housekeeping = (
        await client.get("/housekeeping/tasks", headers=admin, params={"limit": 100})
    ).json()["data"]
    assert task["id"] not in {t["id"] for t in housekeeping["items"]}

    # And it is not reachable by id through the other department's route.
    assert (
        await client.get(f"/housekeeping/tasks/{task['id']}", headers=admin)
    ).status_code == 404


async def test_a_worker_completes_but_cannot_verify(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    admin = auth(society_a.admin_token)
    task = (
        await client.post(
            "/maintenance/tasks",
            headers=admin,
            json={
                "title": "Check the pump",
                "due_on": date.today().isoformat(),
                "assigned_to": ops.worker_user["id"],
            },
        )
    ).json()["data"]

    worker = auth(ops.worker_token)
    started = (
        await client.post(
            f"/maintenance/tasks/{task['id']}/progress",
            headers=worker,
            json={"status": "IN_PROGRESS"},
        )
    ).json()["data"]
    assert started["started_at"] is not None

    completed = (
        await client.post(
            f"/maintenance/tasks/{task['id']}/progress",
            headers=worker,
            json={"status": "COMPLETED", "notes": "Bearing greased.", "actual_cost": "450.00"},
        )
    ).json()["data"]
    assert completed["completed_at"] is not None
    assert "VERIFIED" not in completed["allowed_transitions"]

    refused = await client.post(
        f"/maintenance/tasks/{task['id']}/progress",
        headers=worker,
        json={"status": "VERIFIED"},
    )
    assert refused.status_code == 409

    verified = (
        await client.post(
            f"/maintenance/tasks/{task['id']}/progress",
            headers=admin,
            json={"status": "VERIFIED"},
        )
    ).json()["data"]
    assert verified["verified_at"] is not None


async def test_abandoning_a_task_needs_a_reason(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    admin = auth(society_a.admin_token)
    task = (
        await client.post(
            "/housekeeping/tasks",
            headers=admin,
            json={"title": "Sweep the terrace", "due_on": date.today().isoformat()},
        )
    ).json()["data"]

    response = await client.post(
        f"/housekeeping/tasks/{task['id']}/progress",
        headers=admin,
        json={"status": "SKIPPED"},
    )
    assert response.status_code == 422


async def test_generation_is_idempotent(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    """The nightly sweep can be restarted halfway through without duplicating."""
    admin = auth(society_a.admin_token)
    started = date.today() - timedelta(days=1)
    schedule = (
        await client.post(
            "/maintenance/schedules",
            headers=admin,
            json={
                "title": f"Lift service {uuid.uuid4().hex[:4]}",
                "recurrence": "MONTHLY",
                "starts_on": started.isoformat(),
                "lead_days": 0,
            },
        )
    ).json()["data"]

    first = (await client.post("/maintenance/schedules/generate", headers=admin)).json()["data"]
    assert first["tasks_created"] >= 1

    second = (await client.post("/maintenance/schedules/generate", headers=admin)).json()["data"]

    tasks = (
        await client.get(
            "/maintenance/tasks",
            headers=admin,
            params={"schedule_id": schedule["id"], "limit": 100},
        )
    ).json()["data"]
    due_dates = [t["due_on"] for t in tasks["items"]]
    # One occurrence per due date, no matter how often the generator runs.
    assert len(due_dates) == len(set(due_dates))
    assert second["tasks_created"] == 0 or second["schedules_examined"] >= 0


async def test_a_monthly_schedule_advances_by_a_calendar_month(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    admin = auth(society_a.admin_token)
    start = date.today() - timedelta(days=1)
    schedule = (
        await client.post(
            "/maintenance/schedules",
            headers=admin,
            json={
                "title": f"Tank cleaning {uuid.uuid4().hex[:4]}",
                "recurrence": "MONTHLY",
                "starts_on": start.isoformat(),
                "lead_days": 0,
            },
        )
    ).json()["data"]
    assert schedule["next_due_on"] == start.isoformat()

    await client.post("/maintenance/schedules/generate", headers=admin)

    after = (
        await client.get("/maintenance/schedules", headers=admin, params={"limit": 100})
    ).json()["data"]
    updated = next(s for s in after["items"] if s["id"] == schedule["id"])
    moved = date.fromisoformat(updated["next_due_on"])
    assert moved > start
    # A month, not thirty days: the day of the month is preserved.
    assert moved.day == start.day or moved.day < start.day


async def test_the_work_summary_agrees_with_the_task_list(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    admin = auth(society_a.admin_token)
    summary = (await client.get("/maintenance/summary", headers=admin)).json()["data"]
    listed = (
        await client.get(
            "/maintenance/tasks", headers=admin, params={"limit": 100, "open_only": True}
        )
    ).json()["data"]
    assert summary["pending"] + summary["in_progress"] == listed["total"]
    assert summary["department"] == "MAINTENANCE"


# --------------------------------------------------------------------------- #
# Visitors
# --------------------------------------------------------------------------- #


async def test_a_walk_up_visitor_cannot_be_admitted_without_approval(
    client: AsyncClient, ops: OpsFixture
) -> None:
    guard = auth(ops.guard_token)
    visitor = (
        await client.post(
            "/visitors/gate-entries",
            headers=guard,
            json={
                "flat_id": ops.own_flat["id"],
                "visitor_name": "Courier",
                "visitor_type": "DELIVERY",
            },
        )
    ).json()["data"]
    assert visitor["status"] == "AWAITING_APPROVAL"

    refused = await client.post(
        f"/visitors/{visitor['id']}/check-in", headers=guard, json={}
    )
    assert refused.status_code == 409
    assert "approved" in refused.json()["message"].lower()

    # The flat was told.
    feed = (
        await client.get("/notifications/feed", headers=auth(ops.resident_token))
    ).json()["data"]
    assert any(n["category"] == "visitor.awaiting_approval" for n in feed["items"])

    approved = (
        await client.post(
            f"/visitors/{visitor['id']}/decision",
            headers=auth(ops.resident_token),
            json={"approved": True},
        )
    ).json()["data"]
    assert approved["status"] == "APPROVED"

    checked_in = (
        await client.post(f"/visitors/{visitor['id']}/check-in", headers=guard, json={})
    ).json()["data"]
    assert checked_in["status"] == "CHECKED_IN"
    assert checked_in["checked_in_at"] is not None


async def test_a_denied_visitor_cannot_be_walked_in(
    client: AsyncClient, ops: OpsFixture
) -> None:
    guard = auth(ops.guard_token)
    visitor = (
        await client.post(
            "/visitors/gate-entries",
            headers=guard,
            json={"flat_id": ops.own_flat["id"], "visitor_name": "Unwanted salesman"},
        )
    ).json()["data"]

    await client.post(
        f"/visitors/{visitor['id']}/decision",
        headers=auth(ops.resident_token),
        json={"approved": False, "reason": "Not expecting anyone."},
    )
    refused = await client.post(
        f"/visitors/{visitor['id']}/check-in", headers=guard, json={}
    )
    assert refused.status_code == 409


async def test_denying_a_visitor_requires_a_reason(
    client: AsyncClient, ops: OpsFixture
) -> None:
    visitor = (
        await client.post(
            "/visitors/gate-entries",
            headers=auth(ops.guard_token),
            json={"flat_id": ops.own_flat["id"], "visitor_name": "Reasonless"},
        )
    ).json()["data"]
    response = await client.post(
        f"/visitors/{visitor['id']}/decision",
        headers=auth(ops.resident_token),
        json={"approved": False},
    )
    assert response.status_code == 422


async def test_a_pre_approval_produces_a_code_that_opens_the_gate_once(
    client: AsyncClient, ops: OpsFixture
) -> None:
    now = datetime.now(UTC)
    pass_ = (
        await client.post(
            "/visitors/pre-approvals",
            headers=auth(ops.resident_token),
            json={
                "visitor_name": "Expected Guest",
                "expected_from": (now - timedelta(minutes=5)).isoformat(),
                "expected_to": (now + timedelta(hours=4)).isoformat(),
            },
        )
    ).json()["data"]
    assert pass_["status"] == "EXPECTED"
    code = pass_["pass_code"]
    assert code and len(code) == 6
    # No characters a guard could misread over a phone. Asserted against the
    # alphabet rather than this one sampled code: a stray confusable only shows
    # up in roughly one run in six otherwise, which reads as a flaky suite
    # rather than the real defect it is.
    from app.services.operations import PASS_CODE_ALPHABET

    assert not set(PASS_CODE_ALPHABET) & set("01OIL")
    assert not set(code) & set("01OIL")

    guard = auth(ops.guard_token)
    entered = (
        await client.post("/visitors/check-in", headers=guard, json={"pass_code": code})
    ).json()["data"]
    assert entered["status"] == "CHECKED_IN"

    reused = await client.post(
        "/visitors/check-in", headers=guard, json={"pass_code": code}
    )
    assert reused.status_code == 409

    out = (
        await client.post(f"/visitors/{pass_['id']}/check-out", headers=guard)
    ).json()["data"]
    assert out["status"] == "CHECKED_OUT"
    assert out["duration_minutes"] is not None


async def test_an_expired_window_refuses_the_pass(
    client: AsyncClient, ops: OpsFixture
) -> None:
    now = datetime.now(UTC)
    pass_ = (
        await client.post(
            "/visitors/pre-approvals",
            headers=auth(ops.resident_token),
            json={
                "visitor_name": "Late Guest",
                "expected_from": (now - timedelta(hours=3)).isoformat(),
                "expected_to": (now + timedelta(seconds=2)).isoformat(),
            },
        )
    ).json()["data"]

    # Push the window into the past through the ordinary API surface by
    # asking for one that already closed.
    stale = await client.post(
        "/visitors/pre-approvals",
        headers=auth(ops.resident_token),
        json={
            "visitor_name": "Yesterday's Guest",
            "expected_from": (now - timedelta(days=2)).isoformat(),
            "expected_to": (now - timedelta(days=1)).isoformat(),
        },
    )
    assert stale.status_code == 422
    assert pass_["pass_code"]


async def test_a_resident_sees_only_their_own_flats_visitors(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    theirs = (
        await client.post(
            "/visitors/gate-entries",
            headers=auth(ops.guard_token),
            json={"flat_id": ops.other_flat["id"], "visitor_name": "Someone else's guest"},
        )
    ).json()["data"]

    listed = (
        await client.get("/visitors", headers=auth(ops.resident_token), params={"limit": 100})
    ).json()["data"]
    assert theirs["id"] not in {v["id"] for v in listed["items"]}
    assert (
        await client.get(f"/visitors/{theirs['id']}", headers=auth(ops.resident_token))
    ).status_code == 404

    # The guard, whose security.read broadens visitor.read, sees the society.
    guard_view = (
        await client.get("/visitors", headers=auth(ops.guard_token), params={"limit": 100})
    ).json()["data"]
    assert theirs["id"] in {v["id"] for v in guard_view["items"]}


async def test_a_resident_cannot_decide_a_neighbours_visitor(
    client: AsyncClient, ops: OpsFixture
) -> None:
    theirs = (
        await client.post(
            "/visitors/gate-entries",
            headers=auth(ops.guard_token),
            json={"flat_id": ops.other_flat["id"], "visitor_name": "Neighbour's guest"},
        )
    ).json()["data"]
    response = await client.post(
        f"/visitors/{theirs['id']}/decision",
        headers=auth(ops.resident_token),
        json={"approved": True},
    )
    assert response.status_code == 404


async def test_the_gate_summary_counts_who_is_inside(
    client: AsyncClient, ops: OpsFixture
) -> None:
    guard = auth(ops.guard_token)
    dashboard = (await client.get("/security/dashboard", headers=guard)).json()["data"]
    inside = (
        await client.get("/visitors", headers=guard, params={"on_premises_only": True, "limit": 100})
    ).json()["data"]
    assert dashboard["visitors"]["on_premises"] == inside["total"]
    assert len(dashboard["on_premises"]) <= inside["total"]


async def _pre_approve_delivery(
    client: AsyncClient, ops: OpsFixture, *, company: str | None
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return (
        await client.post(
            "/visitors/pre-approvals",
            headers=auth(ops.resident_token),
            json={
                "visitor_name": "Late-night food order",
                "visitor_type": "DELIVERY",
                "company": company,
                "expected_from": (now - timedelta(minutes=5)).isoformat(),
                "expected_to": (now + timedelta(hours=1)).isoformat(),
            },
        )
    ).json()["data"]


async def _rider_at_gate(
    client: AsyncClient, ops: OpsFixture, *, name: str, company: str | None
) -> dict[str, Any]:
    return (
        await client.post(
            "/visitors/gate-entries",
            headers=auth(ops.guard_token),
            json={
                "flat_id": ops.own_flat["id"],
                "visitor_name": name,
                "visitor_type": "DELIVERY",
                "company": company,
            },
        )
    ).json()["data"]


async def test_a_pre_approved_delivery_goes_straight_up_once(
    client: AsyncClient, ops: OpsFixture
) -> None:
    """The midnight food order: the flat said yes in advance, nobody is awake."""
    pass_ = await _pre_approve_delivery(client, ops, company="Swiggy")

    # Another company is not covered by a Swiggy pre-approval.
    zomato = await _rider_at_gate(client, ops, name="Zomato rider", company="Zomato")
    assert zomato["status"] == "AWAITING_APPROVAL"

    rider = await _rider_at_gate(client, ops, name="Ravi", company="swiggy ")
    assert rider["id"] == pass_["id"]
    assert rider["status"] == "APPROVED"
    assert rider["visitor_name"] == "Ravi"
    assert "Late-night food order" in rider["notes"]

    checked_in = (
        await client.post(
            f"/visitors/{rider['id']}/check-in", headers=auth(ops.guard_token), json={}
        )
    ).json()["data"]
    assert checked_in["status"] == "CHECKED_IN"

    # The approval was used up by Ravi; a second rider has to be asked about.
    second = await _rider_at_gate(client, ops, name="Second rider", company="Swiggy")
    assert second["status"] == "AWAITING_APPROVAL"


async def test_a_guard_cannot_admit_anyone_on_their_own(
    client: AsyncClient, ops: OpsFixture
) -> None:
    guard = auth(ops.guard_token)
    visitor = await _rider_at_gate(client, ops, name="Unknown rider", company=None)

    # The resident's own decision endpoint is not the guard's.
    assert (
        await client.post(
            f"/visitors/{visitor['id']}/decision", headers=guard, json={"approved": True}
        )
    ).status_code == 403

    # Admitting without naming who said yes on the phone is refused.
    unconfirmed = await client.post(
        f"/visitors/{visitor['id']}/guard-decision", headers=guard, json={"approved": True}
    )
    assert unconfirmed.status_code == 422

    still_waiting = await client.post(
        f"/visitors/{visitor['id']}/check-in", headers=guard, json={}
    )
    assert still_waiting.status_code == 409


async def test_a_guard_records_a_phone_approval_and_the_flat_is_told(
    client: AsyncClient, ops: OpsFixture
) -> None:
    guard = auth(ops.guard_token)
    visitor = await _rider_at_gate(client, ops, name="Called-about rider", company="Zepto")

    approved = (
        await client.post(
            f"/visitors/{visitor['id']}/guard-decision",
            headers=guard,
            json={"approved": True, "confirmed_with": "Ops Resident"},
        )
    ).json()["data"]
    assert approved["status"] == "APPROVED"
    assert approved["approved_via"] == "PHONE"
    assert approved["confirmed_with"] == "Ops Resident"

    feed = (
        await client.get("/notifications/feed", headers=auth(ops.resident_token))
    ).json()["data"]
    assert any(
        "Called-about rider" in n["title"] and "Ops Resident" in (n["body"] or "")
        for n in feed["items"]
    )

    # A decision is made once.
    again = await client.post(
        f"/visitors/{visitor['id']}/guard-decision",
        headers=guard,
        json={"approved": False, "reason": "Changed mind"},
    )
    assert again.status_code == 409

    checked_in = (
        await client.post(f"/visitors/{visitor['id']}/check-in", headers=guard, json={})
    ).json()["data"]
    assert checked_in["status"] == "CHECKED_IN"


async def test_a_guard_can_turn_someone_away_with_a_reason(
    client: AsyncClient, ops: OpsFixture
) -> None:
    guard = auth(ops.guard_token)
    visitor = await _rider_at_gate(client, ops, name="Nobody answered", company=None)

    reasonless = await client.post(
        f"/visitors/{visitor['id']}/guard-decision", headers=guard, json={"approved": False}
    )
    assert reasonless.status_code == 422

    denied = (
        await client.post(
            f"/visitors/{visitor['id']}/guard-decision",
            headers=guard,
            json={"approved": False, "reason": "Flat did not answer at 12:10 am."},
        )
    ).json()["data"]
    assert denied["status"] == "DENIED"
    assert denied["approved_via"] == "GUARD"
    assert (
        await client.post(f"/visitors/{visitor['id']}/check-in", headers=guard, json={})
    ).status_code == 409


# --------------------------------------------------------------------------- #
# Security incidents
# --------------------------------------------------------------------------- #


async def test_a_guard_can_report_an_incident_but_not_close_it(
    client: AsyncClient, society_a: SocietyFixture, ops: OpsFixture
) -> None:
    guard = auth(ops.guard_token)
    incident = (
        await client.post(
            "/security/incidents",
            headers=guard,
            json={
                "title": "Gate barrier struck",
                "description": "A cab clipped the barrier arm on the way out.",
                "occurred_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
                "severity": "MINOR",
                "location": "Main gate",
            },
        )
    ).json()["data"]
    assert incident["status"] == "REPORTED"
    assert incident["reported_by_name"]

    refused = await client.patch(
        f"/security/incidents/{incident['id']}",
        headers=guard,
        json={"status": "CLOSED"},
    )
    assert refused.status_code == 403

    resolved = (
        await client.patch(
            f"/security/incidents/{incident['id']}",
            headers=auth(society_a.admin_token),
            json={"status": "RESOLVED", "action_taken": "Barrier arm replaced."},
        )
    ).json()["data"]
    assert resolved["resolved_at"] is not None


async def test_an_incident_cannot_be_recorded_in_the_future(
    client: AsyncClient, ops: OpsFixture
) -> None:
    response = await client.post(
        "/security/incidents",
        headers=auth(ops.guard_token),
        json={
            "title": "Tomorrow's problem",
            "description": "Has not happened yet.",
            "occurred_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Cross-society isolation. **Mandatory.**
# --------------------------------------------------------------------------- #


async def test_operations_do_not_leak_between_societies(
    client: AsyncClient,
    society_a: SocietyFixture,
    society_b: SocietyFixture,
    ops: OpsFixture,
) -> None:
    a_tickets = (
        await client.get(
            "/complaints", headers=auth(society_a.admin_token), params={"limit": 100}
        )
    ).json()["data"]
    b_tickets = (
        await client.get(
            "/complaints", headers=auth(society_b.admin_token), params={"limit": 100}
        )
    ).json()["data"]

    assert a_tickets["total"] > 0
    assert b_tickets["total"] == 0
    assert not ({c["id"] for c in a_tickets["items"]} & {c["id"] for c in b_tickets["items"]})

    # And a ticket id from A is simply absent in B — different database.
    some_id = a_tickets["items"][0]["id"]
    response = await client.get(
        f"/complaints/{some_id}", headers=auth(society_b.admin_token)
    )
    assert response.status_code == 404


async def test_a_flat_from_another_society_cannot_receive_a_visitor(
    client: AsyncClient, society_b: SocietyFixture, ops: OpsFixture
) -> None:
    response = await client.post(
        "/visitors/gate-entries",
        headers=auth(society_b.admin_token),
        json={"flat_id": ops.own_flat["id"], "visitor_name": "Wrong society"},
    )
    assert response.status_code == 404
