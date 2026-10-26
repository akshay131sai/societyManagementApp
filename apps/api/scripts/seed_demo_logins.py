"""Seed a demo society with one login per role, through the public API.

    python scripts/seed_demo_logins.py --super-admin you@example.com
    python scripts/seed_demo_logins.py --base-url http://127.0.0.1:8001/api/v1 ...

Requires ``AUTH_PROVIDER=dev``: it signs in by exchanging ``dev:<email>`` at ``/auth/login``.
Going through HTTP rather than the services means provisioning, RBAC checks and
the central ``platform_users`` rows all happen exactly as they do from the UI.
Safe to re-run — anything that already exists is reused.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DOMAIN = "demo.nestflow.in"
SOCIETY_SLUG = "demo-heights"

USERS = [
    ("FLAT_OWNER", "owner", "Demo Flat Owner"),
    ("MAINTENANCE_ADMIN", "maintenance.admin", "Demo Maintenance Admin"),
    ("MAINTENANCE", "maintenance", "Demo Maintenance Staff"),
    ("HOUSEKEEPER_ADMIN", "housekeeping.admin", "Demo Housekeeping Admin"),
    ("HOUSEKEEPER", "housekeeper", "Demo Housekeeper"),
    ("SECURITY_ADMIN", "security.admin", "Demo Security Admin"),
    ("SECURITY", "security", "Demo Security Guard"),
]


class Api:
    def __init__(self, base_url: str, email: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = ""
        # Exchange the dev identity for an access token, as the web app does.
        self.token = self.call("POST", "/auth/login", {"id_token": f"dev:{email.lower()}"})[
            "access_token"
        ]

    def call(self, method: str, path: str, body: dict[str, Any] | None = None, **query: Any) -> Any:
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        request = urllib.request.Request(
            url,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read() or b"null").get("data")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise SystemExit(f"  {method} {path} failed ({exc.code}): {detail}") from None


def seed(base_url: str, super_admin: str) -> int:
    platform = Api(base_url, super_admin)
    admin_email = f"society.admin@{DOMAIN}"

    societies = platform.call("GET", "/platform/societies", q=SOCIETY_SLUG, limit=100)["items"]
    if any(s["slug"] == SOCIETY_SLUG for s in societies):
        print(f"  society exists: {SOCIETY_SLUG}")
    else:
        platform.call(
            "POST",
            "/platform/societies",
            {
                "name": "Demo Heights",
                "slug": SOCIETY_SLUG,
                "city": "Pune",
                "state": "Maharashtra",
                "pincode": "411001",
                "contact_email": admin_email,
                "contact_phone": "9876500000",
                "admin": {"email": admin_email, "display_name": "Demo Society Admin"},
            },
        )
        print(f"  society created: {SOCIETY_SLUG}")

    society = Api(base_url, admin_email)
    society.call("GET", "/auth/me")  # binds the pending admin account

    user_ids: dict[str, str] = {}
    for role, local, name in USERS:
        email = f"{local}@{DOMAIN}"
        found = [u for u in society.call("GET", "/users", q=email, limit=100)["items"]
                 if u["email"] == email]
        if found:
            user_ids[role] = found[0]["id"]
            print(f"  user exists:  {email}")
        else:
            user = society.call(
                "POST", "/users", {"email": email, "full_name": name, "role_codes": [role]}
            )
            user_ids[role] = user["id"]
            print(f"  user created: {email} ({role})")

    flat_id = _ensure_flat(society)
    owner_email = f"owner@{DOMAIN}"
    residents = society.call("GET", "/residents", q=owner_email, limit=100)["items"]
    if any(r.get("email") == owner_email for r in residents):
        print("  owner already linked to flat A-101")
    else:
        society.call(
            "POST",
            "/residents",
            {
                "flat_id": flat_id,
                "full_name": "Demo Flat Owner",
                "email": owner_email,
                "resident_type": "OWNER",
                "is_primary": True,
                "user_id": user_ids["FLAT_OWNER"],
            },
        )
        print("  owner linked to flat A-101")
    return 0


def _ensure_flat(api: Api) -> str:
    """Building DEMO > block A > floor 1 > flat A-101, reusing what exists."""
    building = next((b for b in api.call("GET", "/buildings") if b["code"] == "DEMO"), None)
    if building is None:
        building = api.call("POST", "/buildings", {"name": "Demo Tower", "code": "DEMO"})

    # A new building comes with one default block; use it (or wing A) if present.
    blocks = api.call("GET", "/blocks", building_id=building["id"])
    block = next((b for b in blocks if b["code"] == "A"), blocks[0] if blocks else None)
    if block is None:
        block = api.call(
            "POST", "/blocks", {"building_id": building["id"], "name": "Wing A", "code": "A"}
        )

    floor = next(
        (f for f in api.call("GET", "/floors", block_id=block["id"]) if f["number"] == 1), None
    )
    if floor is None:
        floor = api.call("POST", "/floors", {"block_id": block["id"], "number": 1})

    flats = api.call("GET", "/flats", q="A-101", limit=100)["items"]
    flat = next((f for f in flats if f["flat_number"] == "A-101"), None)
    if flat is None:
        flat = api.call(
            "POST",
            "/flats",
            {
                "floor_id": floor["id"],
                "flat_number": "A-101",
                "flat_type": "2BHK",
                "area_sqft": "950",
                "occupancy_status": "OWNER_OCCUPIED",
            },
        )
    return str(flat["id"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8001/api/v1")
    parser.add_argument("--super-admin", required=True, help="existing super admin email")
    args = parser.parse_args()
    code = seed(args.base_url, args.super_admin)
    print(f"\n  Logins (any password): society.admin@{DOMAIN}, "
          + ", ".join(f"{local}@{DOMAIN}" for _, local, _ in USERS))
    return code


if __name__ == "__main__":
    sys.exit(main())
