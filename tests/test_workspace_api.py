"""Real authenticated M2 listing contracts, owner isolation and pagination."""

import pytest
from test_credits import authenticate
from workspace_fixture import seed_workspace

from zoclip.credits.schemas import EntitlementView, PlanView, TransactionPage, WalletView
from zoclip.media.schemas import JobView, VideoView
from zoclip.rendering.schemas import ClipView

pytestmark = pytest.mark.integration
LISTS = [("videos", VideoView), ("jobs", JobView), ("clips", ClipView)]
PRIVATE = [
    "/api/v1/me",
    "/api/v1/videos",
    "/api/v1/jobs",
    "/api/v1/clips",
    "/api/v1/me/credits",
    "/api/v1/me/credit-transactions",
    "/api/v1/me/entitlements",
]


@pytest.fixture
def workspace(app):
    return seed_workspace(app.state.session_factory)["users"]


@pytest.mark.parametrize("path", PRIVATE)
def test_workspace_reads_require_authentication(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("resource,schema", LISTS)
def test_listing_pagination_is_owner_scoped_and_retention_aware(
    client, app, workspace, resource, schema
):
    alice, bob = workspace["alice"], workspace["bob"]
    authenticate(client, app, alice["id"])
    first = client.get(f"/api/v1/{resource}?limit=20")
    assert first.status_code == 200
    rows = first.json()
    assert len(rows) == 20
    for row in rows:
        schema.model_validate(row)
        assert row["id"] in alice[resource]
        assert "private_fixture_value" not in str(row)
    second = client.get(f"/api/v1/{resource}?limit=20&before={rows[-1]['id']}")
    all_ids = [row["id"] for row in rows + second.json()]
    assert all_ids == alice[resource]
    foreign = client.get(f"/api/v1/{resource}?before={bob[resource][0]}")
    assert foreign.status_code == 404
    assert client.get(f"/api/v1/{resource}?limit=101").status_code == 422
    assert client.get(f"/api/v1/{resource}?before=bad-id").status_code == 422
    authenticate(client, app, bob["id"])
    assert [row["id"] for row in client.get(f"/api/v1/{resource}").json()] == bob[resource]


def test_balance_ledger_entitlements_and_catalog_match_contracts(client, app, workspace):
    alice, bob = workspace["alice"], workspace["bob"]
    authenticate(client, app, alice["id"])
    wallet = WalletView.model_validate(client.get("/api/v1/me/credits").json())
    assert wallet.available_credits == alice["available_credits"] == 1506
    assert wallet.reserved_credits == 0
    history, cursor = [], None
    while True:
        page = TransactionPage.model_validate(
            client.get(
                "/api/v1/me/credit-transactions",
                params={"limit": 20, **({"cursor": cursor} if cursor else {})},
            ).json()
        )
        history.extend(page.items)
        if page.next_cursor is None:
            break
        cursor = str(page.next_cursor)
    assert len(history) == 42
    assert len({row.id for row in history}) == 42
    assert sum(row.available_delta for row in history) == wallet.available_credits
    assert sum(row.reserved_delta for row in history) == wallet.reserved_credits
    first = client.get("/api/v1/me/entitlements?limit=20").json()
    second = client.get(f"/api/v1/me/entitlements?cursor={first[-1]['id']}").json()
    assert len(first) == 20 and len(second) == 1
    assert len({row["id"] for row in first + second}) == 21
    assert sum(EntitlementView.model_validate(row).active for row in first + second) == 1
    catalog = [PlanView.model_validate(row) for row in client.get("/api/v1/plans").json()]
    creator = next(plan for plan in catalog if plan.slug == "creator")
    assert creator.price.price_paisa == 12345 and not creator.auto_renews
    assert all(plan.price is None for plan in catalog if plan.slug != "creator")
    authenticate(client, app, bob["id"])
    assert client.get("/api/v1/me/credits").json()["available_credits"] == 47
    assert len(client.get("/api/v1/me/credit-transactions").json()["items"]) == 1
    assert client.get("/api/v1/me/entitlements").json() == []
