"""Billing integration: templates, versions, runs, immutability, payments.

The two properties that matter most are tested against the real database,
because both are enforced there:

* a new template version never changes an existing bill;
* a published bill cannot be modified, even by raw SQL.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import SocietyFixture, auth

pytestmark = pytest.mark.asyncio

V = lambda v: {"type": "VALUE", "value": str(v)}  # noqa: E731
F = lambda f: {"type": "FIELD", "field": f}  # noqa: E731

BASIC_FORMULA: dict[str, Any] = {
    "line_items": [
        {"code": "BASE", "label": "Base maintenance", "sort_order": 1,
         "node": F("base_maintenance")},
        {"code": "AREA", "label": "Area charges", "sort_order": 2,
         "quantity_field": "flat_area", "unit": "sqft",
         "node": {"type": "MULTIPLY", "children": [F("flat_area"), V("2.00")]}},
    ]
}


class BillingFixture:
    def __init__(self) -> None:
        self.template: dict[str, Any] = {}
        self.building: dict[str, Any] = {}
        self.flats: list[dict[str, Any]] = []


@pytest_asyncio.fixture(scope="module")
async def billing(client: AsyncClient, society_a: SocietyFixture) -> BillingFixture:
    """A building with three flats and a template assigned to them."""
    admin = auth(society_a.admin_token)
    fixture = BillingFixture()
    tag = uuid.uuid4().hex[:5].upper()

    fixture.building = (
        await client.post("/buildings", headers=admin, json={"name": f"Bill {tag}", "code": tag})
    ).json()["data"]
    block = (
        await client.get("/blocks", headers=admin, params={"building_id": fixture.building["id"]})
    ).json()["data"][0]
    floor = (
        await client.post("/floors", headers=admin, json={"block_id": block["id"], "number": 1})
    ).json()["data"]

    for i, area in enumerate([1000, 1200, 1500], start=1):
        flat = (
            await client.post(
                "/flats",
                headers=admin,
                json={
                    "floor_id": floor["id"],
                    "flat_number": f"{tag}-10{i}",
                    "area_sqft": area,
                    "flat_type": "2BHK" if area < 1400 else "3BHK",
                },
            )
        ).json()["data"]
        fixture.flats.append(flat)

    fixture.template = (
        await client.post(
            "/bill-templates",
            headers=admin,
            json={
                "name": f"Template {tag}",
                "frequency": "MONTHLY",
                "formula": BASIC_FORMULA,
                "parameters": {"base_maintenance": "3000"},
            },
        )
    ).json()["data"]

    await client.post(
        "/bill-assignments",
        headers=admin,
        json={
            "template_id": fixture.template["id"],
            "scope": "BUILDING",
            "building_id": fixture.building["id"],
        },
    )
    return fixture


# --------------------------------------------------------------------------- #
# Templates and versions
# --------------------------------------------------------------------------- #


async def test_template_starts_at_version_one(
    client: AsyncClient, society_a: SocietyFixture, billing: BillingFixture
) -> None:
    detail = (
        await client.get(
            f"/bill-templates/{billing.template['id']}", headers=auth(society_a.admin_token)
        )
    ).json()["data"]
    assert detail["version_count"] >= 1
    v1 = next(v for v in detail["versions"] if v["version_number"] == 1)
    assert v1["formula"]["line_items"][0]["code"] == "BASE"


async def test_invalid_formula_is_refused_at_save(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    response = await client.post(
        "/bill-templates",
        headers=auth(society_a.admin_token),
        json={
            "name": f"Bad {uuid.uuid4().hex[:5]}",
            "formula": {"line_items": [{"code": "X", "label": "x", "node": F("nonsense")}]},
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert any(
        e["code"] == "UNKNOWN_FIELD" for e in response.json()["details"]["errors"]
    )


async def test_duplicate_template_name_refused(
    client: AsyncClient, society_a: SocietyFixture, billing: BillingFixture
) -> None:
    response = await client.post(
        "/bill-templates",
        headers=auth(society_a.admin_token),
        json={"name": billing.template["name"], "formula": BASIC_FORMULA},
    )
    assert response.status_code == 409


async def test_field_catalogue_drives_the_palette(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    fields = (await client.get("/billing/fields", headers=auth(society_a.admin_token))).json()["data"]
    keys = {f["key"] for f in fields}
    assert {"flat_area", "base_maintenance", "water_consumption", "period_months"} <= keys


async def test_preview_evaluates_against_a_real_flat(
    client: AsyncClient, society_a: SocietyFixture, billing: BillingFixture
) -> None:
    response = await client.post(
        "/billing/preview",
        headers=auth(society_a.admin_token),
        json={
            "formula": BASIC_FORMULA,
            "parameters": {"base_maintenance": "3000"},
            "flat_id": billing.flats[0]["id"],
        },
    )
    data = response.json()["data"]
    assert data["valid"]
    assert data["flat"]["flat_number"] == billing.flats[0]["flat_number"]
    # 3000 base + 1000 sqft * 2.00
    assert data["total"] == "5000.00"


# --------------------------------------------------------------------------- #
# Assignment resolution
# --------------------------------------------------------------------------- #


async def test_most_specific_assignment_wins(
    client: AsyncClient, society_a: SocietyFixture, billing: BillingFixture
) -> None:
    """A 3BHK-specific template must beat the building-wide one."""
    admin = auth(society_a.admin_token)
    tag = uuid.uuid4().hex[:5].upper()

    special = (
        await client.post(
            "/bill-templates",
            headers=admin,
            json={"name": f"Premium {tag}", "formula": BASIC_FORMULA},
        )
    ).json()["data"]
    await client.post(
        "/bill-assignments",
        headers=admin,
        json={"template_id": special["id"], "scope": "FLAT_TYPE", "flat_type": "3BHK"},
    )

    three_bhk = next(f for f in billing.flats if f["flat_type"] == "3BHK")
    two_bhk = next(f for f in billing.flats if f["flat_type"] == "2BHK")

    for flat, expected in ((three_bhk, special["id"]), (two_bhk, billing.template["id"])):
        explained = (
            await client.get(f"/bill-assignments/explain/{flat['id']}", headers=admin)
        ).json()["data"]
        assert explained["template_id"] == expected, flat["flat_number"]

    # Clean up so later tests see the original assignment set.
    assignments = (
        await client.get("/bill-assignments", headers=admin, params={"template_id": special["id"]})
    ).json()["data"]
    for a in assignments:
        await client.delete(f"/bill-assignments/{a['id']}", headers=admin)
    await client.delete(f"/bill-templates/{special['id']}", headers=admin)


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #


async def test_run_generates_drafts_and_does_not_publish(
    client: AsyncClient, society_a: SocietyFixture, billing: BillingFixture
) -> None:
    admin = auth(society_a.admin_token)
    run = (
        await client.post(
            "/billing/runs",
            headers=admin,
            json={"template_id": billing.template["id"], "period_key": "2026-01"},
        )
    ).json()["data"]

    assert run["status"] == "COMPLETED", "a run must never auto-publish"
    assert run["bills_generated"] == 3
    assert run["bills_failed"] == 0
    # 3000 + area*2 for 1000/1200/1500 sqft
    assert Decimal(run["total_amount"]) == Decimal("16400.00")

    bills = (
        await client.get("/billing/bills", headers=admin, params={"run_id": run["id"]})
    ).json()["data"]
    assert all(b["status"] == "DRAFT" for b in bills["items"])


async def test_double_run_for_the_same_period_is_refused(
    client: AsyncClient, society_a: SocietyFixture, billing: BillingFixture
) -> None:
    admin = auth(society_a.admin_token)
    body = {"template_id": billing.template["id"], "period_key": "2026-02"}
    assert (await client.post("/billing/runs", headers=admin, json=body)).status_code == 201

    second = await client.post("/billing/runs", headers=admin, json=body)
    assert second.status_code == 409
    assert "already been billed" in second.json()["message"]


async def test_period_key_must_match_the_template_frequency(
    client: AsyncClient, society_a: SocietyFixture, billing: BillingFixture
) -> None:
    response = await client.post(
        "/billing/runs",
        headers=auth(society_a.admin_token),
        json={"template_id": billing.template["id"], "period_key": "2026-Q1"},
    )
    assert response.status_code == 422
    assert "quarterly" in response.json()["message"].lower()


async def test_period_options_flag_what_is_already_billed(
    client: AsyncClient, society_a: SocietyFixture, billing: BillingFixture
) -> None:
    periods = (
        await client.get(
            f"/billing/periods/{billing.template['id']}", headers=auth(society_a.admin_token)
        )
    ).json()["data"]
    assert len(periods) == 6
    assert all("already_billed" in p for p in periods)


# --------------------------------------------------------------------------- #
# Publication and immutability
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture(scope="module")
async def published_bill(
    client: AsyncClient, society_a: SocietyFixture, billing: BillingFixture
) -> dict[str, Any]:
    admin = auth(society_a.admin_token)
    run = (
        await client.post(
            "/billing/runs",
            headers=admin,
            json={"template_id": billing.template["id"], "period_key": "2026-03"},
        )
    ).json()["data"]
    await client.post(f"/billing/runs/{run['id']}/publish", headers=admin)
    bills = (
        await client.get("/billing/bills", headers=admin, params={"run_id": run["id"]})
    ).json()["data"]
    return bills["items"][0]


async def test_publishing_makes_bills_published(
    client: AsyncClient, published_bill: dict[str, Any]
) -> None:
    assert published_bill["status"] == "PUBLISHED"
    assert published_bill["issued_at"] is not None
    assert published_bill["bill_number"].startswith("NF/")


async def test_republish_is_refused(
    client: AsyncClient, society_a: SocietyFixture, published_bill: dict[str, Any]
) -> None:
    run_id = published_bill["billing_run_id"]
    response = await client.post(
        f"/billing/runs/{run_id}/publish", headers=auth(society_a.admin_token)
    )
    assert response.status_code == 409


async def test_published_run_cannot_be_discarded(
    client: AsyncClient, society_a: SocietyFixture, published_bill: dict[str, Any]
) -> None:
    response = await client.delete(
        f"/billing/runs/{published_bill['billing_run_id']}",
        headers=auth(society_a.admin_token),
    )
    assert response.status_code == 409


async def test_published_bill_is_immutable_in_the_database(
    society_a: SocietyFixture, published_bill: dict[str, Any]
) -> None:
    """Attempted directly in SQL, bypassing every application safeguard.

    If the trigger were missing, an ORM bug or a stray script could rewrite a
    financial record silently.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from app.database.manager import get_tenant_manager

    manager = get_tenant_manager()
    society_id = uuid.UUID(society_a.id)
    bill_id = published_bill["id"]

    for column, value in [
        ("total", "1"),
        ("subtotal", "1"),
        ("formula_snapshot", "'{}'::jsonb"),
        ("input_snapshot", "'{}'::jsonb"),
        ("bill_number", "'NF/HACK/1'"),
    ]:
        with pytest.raises(IntegrityError):
            async with manager.session(society_id) as session:
                await session.execute(
                    text(f"UPDATE maintenance_bills SET {column} = {value} WHERE id = :i"),
                    {"i": bill_id},
                )

    with pytest.raises(IntegrityError):
        async with manager.session(society_id) as session:
            await session.execute(
                text("DELETE FROM maintenance_bills WHERE id = :i"), {"i": bill_id}
            )


async def test_published_template_version_is_immutable_in_the_database(
    society_a: SocietyFixture, billing: BillingFixture
) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from app.database.manager import get_tenant_manager

    manager = get_tenant_manager()
    society_id = uuid.UUID(society_a.id)

    async with manager.session(society_id) as session:
        await session.execute(
            text(
                "UPDATE bill_template_versions SET is_published = true "
                "WHERE template_id = :t AND version_number = 1"
            ),
            {"t": billing.template["id"]},
        )

    with pytest.raises(IntegrityError):
        async with manager.session(society_id) as session:
            await session.execute(
                text(
                    "UPDATE bill_template_versions SET formula = '{}'::jsonb "
                    "WHERE template_id = :t AND version_number = 1"
                ),
                {"t": billing.template["id"]},
            )


async def test_a_new_version_does_not_change_existing_bills(
    client: AsyncClient, society_a: SocietyFixture, billing: BillingFixture,
    published_bill: dict[str, Any],
) -> None:
    """The headline guarantee: raising a rate creates v2 and leaves history alone."""
    admin = auth(society_a.admin_token)

    before = (
        await client.get(f"/billing/bills/{published_bill['id']}", headers=admin)
    ).json()["data"]
    before_calc = (
        await client.get(f"/billing/bills/{published_bill['id']}/calculation", headers=admin)
    ).json()["data"]

    doubled = {
        "line_items": [
            {"code": "BASE", "label": "Base maintenance", "sort_order": 1,
             "node": F("base_maintenance")},
            {"code": "AREA", "label": "Area charges", "sort_order": 2,
             "node": {"type": "MULTIPLY", "children": [F("flat_area"), V("4.00")]}},
        ]
    }
    version = await client.post(
        f"/bill-templates/{billing.template['id']}/versions",
        headers=admin,
        json={"formula": doubled, "parameters": {"base_maintenance": "9000"},
              "notes": "Rate increase", "activate": True},
    )
    assert version.status_code == 201
    assert version.json()["data"]["version_number"] >= 2

    after = (
        await client.get(f"/billing/bills/{published_bill['id']}", headers=admin)
    ).json()["data"]
    after_calc = (
        await client.get(f"/billing/bills/{published_bill['id']}/calculation", headers=admin)
    ).json()["data"]

    assert after["total"] == before["total"]
    assert after["template_version_id"] == before["template_version_id"]
    assert after_calc["formula"] == before_calc["formula"]
    assert after_calc["inputs"] == before_calc["inputs"]


async def test_a_trigger_rejection_reads_as_a_conflict_not_an_outage(
    client: AsyncClient, society_a: SocietyFixture, published_bill: dict[str, Any]
) -> None:
    """The trigger writes a message for a person; the API must surface it.

    Reporting "the database is temporarily unavailable" for an immutable bill
    would send the admin chasing an infrastructure problem that does not exist.
    """
    response = await client.delete(
        f"/billing/runs/{published_bill['billing_run_id']}",
        headers=auth(society_a.admin_token),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"
    assert "unavailable" not in response.json()["message"].lower()


async def test_calculation_is_served_from_the_snapshot(
    client: AsyncClient, society_a: SocietyFixture, published_bill: dict[str, Any]
) -> None:
    calc = (
        await client.get(
            f"/billing/bills/{published_bill['id']}/calculation",
            headers=auth(society_a.admin_token),
        )
    ).json()["data"]

    assert calc["formula"]["line_items"]
    assert calc["inputs"]
    assert calc["trace"]

    total = sum(
        (-1 if li["is_credit"] else 1) * Decimal(li["amount"]) for li in calc["line_items"]
    )
    assert total == Decimal(calc["total"]), "printed rows must add up to the printed total"


# --------------------------------------------------------------------------- #
# Payments
# --------------------------------------------------------------------------- #


async def test_payment_lifecycle(
    client: AsyncClient, society_a: SocietyFixture, billing: BillingFixture
) -> None:
    admin = auth(society_a.admin_token)
    run = (
        await client.post(
            "/billing/runs",
            headers=admin,
            json={"template_id": billing.template["id"], "period_key": "2026-04"},
        )
    ).json()["data"]
    await client.post(f"/billing/runs/{run['id']}/publish", headers=admin)
    bill = (
        await client.get("/billing/bills", headers=admin, params={"run_id": run["id"]})
    ).json()["data"]["items"][0]

    half = (Decimal(bill["total"]) / 2).quantize(Decimal("0.01"))
    first = await client.post(
        "/payments", headers=admin,
        json={"bill_id": bill["id"], "amount": str(half), "method": "UPI"},
    )
    assert first.status_code == 201

    partial = (await client.get(f"/billing/bills/{bill['id']}", headers=admin)).json()["data"]
    assert partial["payment_status"] == "PARTIAL"
    assert Decimal(partial["amount_paid"]) == half

    over = await client.post(
        "/payments", headers=admin,
        json={"bill_id": bill["id"], "amount": bill["total"], "method": "CASH"},
    )
    assert over.status_code == 422, "a payment cannot exceed the balance due"

    await client.post(
        "/payments", headers=admin,
        json={"bill_id": bill["id"], "amount": partial["balance_due"], "method": "NEFT"},
    )
    paid = (await client.get(f"/billing/bills/{bill['id']}", headers=admin)).json()["data"]
    assert paid["payment_status"] == "PAID"
    assert paid["total"] == bill["total"], "paying must never change the amount billed"


async def test_only_published_bills_can_be_paid(
    client: AsyncClient, society_a: SocietyFixture, billing: BillingFixture
) -> None:
    admin = auth(society_a.admin_token)
    run = (
        await client.post(
            "/billing/runs",
            headers=admin,
            json={"template_id": billing.template["id"], "period_key": "2026-05"},
        )
    ).json()["data"]
    draft = (
        await client.get("/billing/bills", headers=admin, params={"run_id": run["id"]})
    ).json()["data"]["items"][0]

    response = await client.post(
        "/payments", headers=admin,
        json={"bill_id": draft["id"], "amount": "100", "method": "CASH"},
    )
    assert response.status_code == 409


# --------------------------------------------------------------------------- #
# Owner scoping and isolation
# --------------------------------------------------------------------------- #


async def test_resident_sees_only_their_own_bills(
    client: AsyncClient, society_a: SocietyFixture, billing: BillingFixture
) -> None:
    admin = auth(society_a.admin_token)
    tag = uuid.uuid4().hex[:5]
    email = f"biller-{tag}@test.nestflow.in"

    user = (
        await client.post(
            "/users", headers=admin,
            json={"email": email, "full_name": "Bill Reader", "role_codes": ["FLAT_OWNER"]},
        )
    ).json()["data"]
    await client.post(
        "/residents", headers=admin,
        json={
            "flat_id": billing.flats[0]["id"],
            "full_name": "Bill Reader",
            "resident_type": "OWNER",
            "user_id": user["id"],
        },
    )
    token = auth(f"dev:{email}")

    admin_view = await client.get("/billing/bills", headers=admin, params={"limit": 1})
    resident_view = await client.get("/billing/bills", headers=token, params={"limit": 100})

    assert admin_view.json()["data"]["total"] > resident_view.json()["data"]["total"]
    assert all(
        b["flat_id"] == billing.flats[0]["id"]
        for b in resident_view.json()["data"]["items"]
    )


async def test_resident_cannot_read_a_neighbours_bill_or_calculation(
    client: AsyncClient, society_a: SocietyFixture, billing: BillingFixture
) -> None:
    admin = auth(society_a.admin_token)
    tag = uuid.uuid4().hex[:5]
    email = f"nosy-{tag}@test.nestflow.in"

    user = (
        await client.post(
            "/users", headers=admin,
            json={"email": email, "full_name": "Nosy", "role_codes": ["FLAT_OWNER"]},
        )
    ).json()["data"]
    await client.post(
        "/residents", headers=admin,
        json={
            "flat_id": billing.flats[0]["id"],
            "full_name": "Nosy",
            "resident_type": "OWNER",
            "user_id": user["id"],
        },
    )
    token = auth(f"dev:{email}")

    neighbour_bills = (
        await client.get(
            "/billing/bills", headers=admin, params={"flat_id": billing.flats[1]["id"], "limit": 1}
        )
    ).json()["data"]["items"]
    if not neighbour_bills:
        pytest.skip("no neighbour bill to probe")
    target = neighbour_bills[0]["id"]

    assert (await client.get(f"/billing/bills/{target}", headers=token)).status_code == 404
    assert (
        await client.get(f"/billing/bills/{target}/calculation", headers=token)
    ).status_code == 404


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/bill-templates"),
        ("get", "/billing/fields"),
        ("get", "/billing/runs"),
        ("get", "/billing/summary"),
    ],
)
async def test_resident_cannot_reach_the_bill_builder(
    client: AsyncClient, society_a: SocietyFixture, billing: BillingFixture,
    method: str, path: str,
) -> None:
    admin = auth(society_a.admin_token)
    tag = uuid.uuid4().hex[:5]
    email = f"denied-{tag}@test.nestflow.in"
    user = (
        await client.post(
            "/users", headers=admin,
            json={"email": email, "full_name": "Denied", "role_codes": ["FLAT_OWNER"]},
        )
    ).json()["data"]
    await client.post(
        "/residents", headers=admin,
        json={
            "flat_id": billing.flats[0]["id"],
            "full_name": "Denied",
            "resident_type": "OWNER",
            "user_id": user["id"],
        },
    )

    response = await getattr(client, method)(path, headers=auth(f"dev:{email}"))
    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


async def test_bills_do_not_leak_between_societies(
    client: AsyncClient, society_a: SocietyFixture, society_b: SocietyFixture,
    billing: BillingFixture,
) -> None:
    in_b = await client.get("/bill-templates", headers=auth(society_b.admin_token))
    assert all(t["id"] != billing.template["id"] for t in in_b.json()["data"])

    foreign = await client.get(
        f"/bill-templates/{billing.template['id']}", headers=auth(society_b.admin_token)
    )
    assert foreign.status_code == 404
