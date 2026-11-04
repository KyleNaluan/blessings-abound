"""Constraint tests on the migrated tables, run against real Postgres."""

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError

TABLES = [
    "profiles",
    "items",
    "item_cards",
    "appraisals",
    "decisions",
    "comp_searches",
    "sign_in_attempts",
    "listing_drafts",
    "settings",
    "listings",
    "sale_events",
    "sync_log",
    "jobs",
    "alembic_version",
]
CHANNEL_SCHEMAS = ["channel_a", "channel_b"]
CHANNEL_TABLES = ["listings", "orders", "controls"]
# The net after fees is the one cents column allowed below zero, see docs/database.md.
SIGNED_CENTS_COLUMNS = {"net_after_fees_cents"}


def insert(connection: Connection, table: str, **values: Any) -> None:
    columns = ", ".join(values)
    params = ", ".join(f":{name}" for name in values)
    connection.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({params})"), values)


def add_profile(connection: Connection, username: str = "tester", **values: Any) -> UUID:
    auth_user_id = uuid4()
    fields = {"display_name": "Test Person"}
    insert(
        connection, "profiles", auth_user_id=auth_user_id, username=username, **(fields | values)
    )
    return auth_user_id


def add_item(connection: Connection, lister_id: UUID, **values: Any) -> UUID:
    item_id = uuid4()
    fields: dict[str, Any] = {"sku": f"T{item_id.hex}", "photo_keys": ["a.jpg"], "photo_hash": "h"}
    insert(connection, "items", id=item_id, lister_id=lister_id, **(fields | values))
    return item_id


def add_appraisal(connection: Connection, item_id: UUID, **values: Any) -> UUID:
    appraisal_id = uuid4()
    fields = {"confidence": "high", "recommendation": "yes", "rules_config": "{}"}
    insert(connection, "appraisals", id=appraisal_id, item_id=item_id, **(fields | values))
    return appraisal_id


def add_card(connection: Connection, item_id: UUID, **values: Any) -> None:
    fields = {
        "category": "apparel",
        "search_query": "nike hoodie",
        "model_confidence": "high",
        "condition": "pre_owned",
    }
    insert(connection, "item_cards", item_id=item_id, **(fields | values))


def add_draft(connection: Connection, item_id: UUID, created_by: UUID, **values: Any) -> None:
    fields = {
        "channel": "channel_a",
        "title": "Nike hoodie - Pre-owned",
        "description": "Nike hoodie, pre-owned.",
        "category": "Men's Clothing",
        "source": "model",
    }
    insert(
        connection,
        "listing_drafts",
        id=uuid4(),
        item_id=item_id,
        created_by=created_by,
        **(fields | values),
    )


def columns_named(connection: Connection, pattern: str) -> list[tuple[str, str, str]]:
    rows = connection.execute(
        text(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name LIKE :pattern"
        ),
        {"pattern": pattern},
    )
    return [(row[0], row[1], row[2]) for row in rows]


def test_every_cents_column_is_a_whole_number_type(connection: Connection) -> None:
    columns = columns_named(connection, "%\\_cents")
    assert len(columns) == 7
    assert {data_type for _, _, data_type in columns} == {"integer"}


def test_fractional_cents_are_refused(connection: Connection) -> None:
    item_id = add_item(connection, add_profile(connection))
    with pytest.raises(DataError):
        add_appraisal(connection, item_id, price_low_cents="12.5")


@pytest.mark.parametrize("column", ["price_low_cents", "price_typical_cents", "price_high_cents"])
def test_negative_cents_are_refused(connection: Connection, column: str) -> None:
    item_id = add_item(connection, add_profile(connection))
    with pytest.raises(IntegrityError, match=f"ck_appraisals_{column}_non_negative"):
        add_appraisal(connection, item_id, **{column: -1})


def test_only_the_net_after_fees_may_be_negative(connection: Connection) -> None:
    item_id = add_item(connection, add_profile(connection))
    add_appraisal(connection, item_id, net_after_fees_cents=-204)
    # A price a manager sets has to be above zero, which also keeps it from going negative.
    signed = {
        column
        for table, column, _ in columns_named(connection, "%\\_cents")
        if not connection.execute(
            text("SELECT 1 FROM pg_constraint WHERE contype = 'c' AND conname = ANY(:names)"),
            {"names": [f"ck_{table}_{column}_{rule}" for rule in ("non_negative", "positive")]},
        ).first()
    }
    assert signed == SIGNED_CENTS_COLUMNS


def test_price_range_must_be_ordered(connection: Connection) -> None:
    item_id = add_item(connection, add_profile(connection))
    with pytest.raises(IntegrityError, match="ck_appraisals_price_range_ordered"):
        add_appraisal(
            connection,
            item_id,
            price_low_cents=500,
            price_typical_cents=400,
            price_high_cents=600,
        )


def test_every_time_column_carries_a_time_zone(connection: Connection) -> None:
    columns = columns_named(connection, "%\\_at")
    assert len(columns) == 29
    assert {data_type for _, _, data_type in columns} == {"timestamp with time zone"}


def test_a_time_with_an_offset_keeps_its_instant(connection: Connection) -> None:
    connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    auth_user_id = add_profile(connection, created_at="2026-10-30 08:00:00-05:00")
    stored = connection.execute(
        text("SELECT created_at::text FROM profiles WHERE auth_user_id = :id"),
        {"id": auth_user_id},
    ).scalar_one()
    assert stored == "2026-10-30 13:00:00+00"


def test_usernames_are_unique(connection: Connection) -> None:
    add_profile(connection, "manager1")
    with pytest.raises(IntegrityError, match="uq_profiles_username"):
        add_profile(connection, "manager1")


@pytest.mark.parametrize("username", ["Manager1", "man ager", ""])
def test_usernames_must_be_lowercase_without_spaces(connection: Connection, username: str) -> None:
    with pytest.raises(IntegrityError, match="ck_profiles_username_format"):
        add_profile(connection, username)


def test_email_is_optional_but_unique_when_given(connection: Connection) -> None:
    add_profile(connection, "no-email-1")
    add_profile(connection, "no-email-2")
    add_profile(connection, "with-email-1", email="person@example.com")
    with pytest.raises(IntegrityError, match="uq_profiles_email"):
        add_profile(connection, "with-email-2", email="person@example.com")


def test_email_must_be_lowercase(connection: Connection) -> None:
    with pytest.raises(IntegrityError, match="ck_profiles_email_lowercase"):
        add_profile(connection, email="Person@example.com")


def test_profile_defaults_to_active_staff(connection: Connection) -> None:
    auth_user_id = add_profile(connection)
    row = connection.execute(
        text("SELECT role, is_active FROM profiles WHERE auth_user_id = :id"),
        {"id": auth_user_id},
    ).one()
    assert tuple(row) == ("staff", True)


@pytest.mark.parametrize(
    ("add_row", "column", "constraint"),
    [
        (lambda c: add_profile(c, role="admin"), "role", "ck_profiles_role"),
        (
            lambda c: add_item(c, add_profile(c), status="lost"),
            "status",
            "ck_items_status",
        ),
        (
            lambda c: add_card(c, add_item(c, add_profile(c)), category="books"),
            "category",
            "ck_item_cards_category",
        ),
        (
            lambda c: add_card(c, add_item(c, add_profile(c)), condition="fine"),
            "condition",
            "ck_item_cards_condition",
        ),
        (
            lambda c: add_card(c, add_item(c, add_profile(c)), flaws=["dusty"]),
            "flaws",
            "ck_item_cards_flaws_known",
        ),
        (
            lambda c: add_appraisal(c, add_item(c, add_profile(c)), recommendation="maybe"),
            "recommendation",
            "ck_appraisals_recommendation",
        ),
    ],
)
def test_unknown_values_are_refused(
    connection: Connection, add_row: Callable[[Connection], Any], column: str, constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        add_row(connection)


def test_skus_are_unique(connection: Connection) -> None:
    lister_id = add_profile(connection)
    add_item(connection, lister_id, sku="RT10272601")
    with pytest.raises(IntegrityError, match="uq_items_sku"):
        add_item(connection, lister_id, sku="RT10272601")


@pytest.mark.parametrize("photo_keys", [[], ["1", "2", "3", "4", "5"]])
def test_an_item_has_one_to_four_photos(connection: Connection, photo_keys: list[str]) -> None:
    with pytest.raises(IntegrityError, match="ck_items_photo_keys_count"):
        add_item(connection, add_profile(connection), photo_keys=photo_keys)


def test_an_item_has_one_card(connection: Connection) -> None:
    item_id = add_item(connection, add_profile(connection))
    add_card(connection, item_id)
    with pytest.raises(IntegrityError, match="pk_item_cards"):
        add_card(connection, item_id)


def test_yes_and_no_decisions_are_both_kept_for_one_item(connection: Connection) -> None:
    person = add_profile(connection)
    item_id = add_item(connection, person)
    appraisal_id = add_appraisal(connection, item_id)
    for choice in ("no", "yes"):
        insert(
            connection,
            "decisions",
            id=uuid4(),
            item_id=item_id,
            appraisal_id=appraisal_id,
            decision=choice,
            decided_by=person,
        )
    count = connection.execute(
        text("SELECT count(*) FROM decisions WHERE item_id = :id"), {"id": item_id}
    ).scalar_one()
    assert count == 2


def test_a_decision_cannot_use_another_items_appraisal(connection: Connection) -> None:
    person = add_profile(connection)
    other_appraisal = add_appraisal(connection, add_item(connection, person))
    with pytest.raises(IntegrityError, match="fk_decisions_appraisal_id_item_id_appraisals"):
        insert(
            connection,
            "decisions",
            id=uuid4(),
            item_id=add_item(connection, person),
            appraisal_id=other_appraisal,
            decision="yes",
            decided_by=person,
        )


def test_a_person_with_past_decisions_cannot_be_deleted(connection: Connection) -> None:
    lister = add_profile(connection, "lister")
    decider = add_profile(connection, "decider")
    item_id = add_item(connection, lister)
    insert(
        connection,
        "decisions",
        id=uuid4(),
        item_id=item_id,
        appraisal_id=add_appraisal(connection, item_id),
        decision="no",
        decided_by=decider,
    )
    with pytest.raises(IntegrityError, match="fk_decisions_decided_by_profiles"):
        connection.execute(text("DELETE FROM profiles WHERE auth_user_id = :id"), {"id": decider})


def test_every_public_table_has_row_level_security_and_no_policies(connection: Connection) -> None:
    rows = connection.execute(
        text("SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public'")
    ).all()
    assert {name for name, _ in rows} == set(TABLES)
    assert all(enabled for _, enabled in rows)
    policies = connection.execute(
        text("SELECT count(*) FROM pg_policies WHERE schemaname = 'public'")
    ).scalar_one()
    assert policies == 0


@pytest.fixture
def web_api_role(connection: Connection) -> Callable[[], None]:
    """A role with the table grants Supabase gives its web API, which is what RLS has to stop."""
    connection.execute(text("CREATE ROLE test_web_api NOLOGIN"))
    connection.execute(text("GRANT USAGE ON SCHEMA public TO test_web_api"))
    connection.execute(text("GRANT ALL ON ALL TABLES IN SCHEMA public TO test_web_api"))

    def become_web_api() -> None:
        connection.execute(text("SET LOCAL ROLE test_web_api"))

    return become_web_api


@pytest.mark.parametrize("table", TABLES)
def test_the_web_api_role_reads_nothing(
    connection: Connection, web_api_role: Callable[[], None], table: str
) -> None:
    person = add_profile(connection)
    add_card(connection, add_item(connection, person))
    add_appraisal(connection, add_item(connection, person))
    web_api_role()
    assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0


def test_the_web_api_role_cannot_write(
    connection: Connection, web_api_role: Callable[[], None]
) -> None:
    web_api_role()
    with pytest.raises(ProgrammingError, match="row-level security"):
        add_profile(connection)


def test_an_item_has_one_draft_per_channel(connection: Connection) -> None:
    lister = add_profile(connection)
    item_id = add_item(connection, lister)
    add_draft(connection, item_id, lister)
    add_draft(connection, item_id, lister, channel="channel_b", category="Menswear")
    with pytest.raises(IntegrityError, match="uq_listing_drafts_item_id_channel"):
        add_draft(connection, item_id, lister)


def test_a_draft_channel_must_be_known(connection: Connection) -> None:
    lister = add_profile(connection)
    with pytest.raises(IntegrityError, match="ck_listing_drafts_channel"):
        add_draft(connection, add_item(connection, lister), lister, channel="channel_c")


def test_a_template_draft_says_why_it_was_used(connection: Connection) -> None:
    lister = add_profile(connection)
    with pytest.raises(IntegrityError, match="ck_listing_drafts_fallback_reason_with_template"):
        add_draft(connection, add_item(connection, lister), lister, source="template")


def test_a_model_draft_has_no_fallback_reason(connection: Connection) -> None:
    lister = add_profile(connection)
    with pytest.raises(IntegrityError, match="ck_listing_drafts_fallback_reason_with_template"):
        add_draft(connection, add_item(connection, lister), lister, fallback_reason="flagged")


def test_a_draft_awaiting_approval_records_who_sent_it(connection: Connection) -> None:
    lister = add_profile(connection)
    add_draft(
        connection,
        add_item(connection, lister),
        lister,
        state="awaiting_approval",
        submitted_by=lister,
        submitted_at="2026-11-03 12:00:00+00:00",
    )
    with pytest.raises(IntegrityError, match="ck_listing_drafts_submitted_after_draft"):
        add_draft(connection, add_item(connection, lister), lister, state="awaiting_approval")


SENT = {"submitted_at": "2026-11-03 12:00:00+00:00"}


@pytest.mark.parametrize("state", ["approved", "rejected"])
def test_a_reviewed_draft_records_which_manager_reviewed_it(
    connection: Connection, state: str
) -> None:
    lister = add_profile(connection)
    sent = SENT | {"submitted_by": lister, "state": state}
    reviewed = {"reviewed_by": lister, "reviewed_at": "2026-11-04 12:00:00+00:00"}
    add_draft(connection, add_item(connection, lister), lister, **sent, **reviewed)
    with pytest.raises(IntegrityError, match="ck_listing_drafts_reviewed_after_approval"):
        add_draft(connection, add_item(connection, lister), lister, **sent)


def test_a_draft_still_waiting_has_no_reviewer(connection: Connection) -> None:
    lister = add_profile(connection)
    with pytest.raises(IntegrityError, match="ck_listing_drafts_reviewed_after_approval"):
        add_draft(
            connection,
            add_item(connection, lister),
            lister,
            **SENT,
            state="awaiting_approval",
            submitted_by=lister,
            reviewed_by=lister,
            reviewed_at="2026-11-04 12:00:00+00:00",
        )


@pytest.mark.parametrize("cents", [0, -1])
def test_a_price_override_is_above_zero(connection: Connection, cents: int) -> None:
    lister = add_profile(connection)
    with pytest.raises(IntegrityError, match="ck_listing_drafts_price_override_cents_positive"):
        add_draft(connection, add_item(connection, lister), lister, price_override_cents=cents)


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"release_month": "2027-01-15"}, "ck_items_release_month_first_day"),
        ({"package_weight_oz": 0, "box_code": "8x6x4"}, "ck_items_package_weight_oz_positive"),
        ({"package_weight_oz": 12.5}, "ck_items_package_weight_with_box"),
        ({"box_code": "8x6x4"}, "ck_items_package_weight_with_box"),
        ({"location_code": "A3"}, "ck_items_location_after_package"),
    ],
)
def test_an_items_package_and_shelf_hang_together(
    connection: Connection, values: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        add_item(connection, add_profile(connection), **values)


def test_an_item_can_be_packaged_shelved_and_held_to_a_month(connection: Connection) -> None:
    add_item(
        connection,
        add_profile(connection),
        release_month="2027-01-01",
        package_weight_oz=12.5,
        box_code="8x6x4",
        location_code="A3",
    )


def add_listing(connection: Connection, channel: str = "channel_a", **values: Any) -> UUID:
    person = add_profile(connection, f"approver-{uuid4().hex[:8]}")
    listing_id = uuid4()
    fields = {
        "item_id": add_item(connection, person),
        "channel": channel,
        "price_cents": 2500,
        "content": "{}",
        "approved_by": person,
        "approved_at": "2026-11-03 12:00:00+00",
    }
    insert(connection, "listings", id=listing_id, **(fields | values))
    return listing_id


def test_an_item_has_one_listing_per_channel(connection: Connection) -> None:
    listing_id = add_listing(connection)
    item_id = connection.execute(
        text("SELECT item_id FROM listings WHERE id = :id"), {"id": listing_id}
    ).scalar_one()
    add_listing(connection, "channel_b", item_id=item_id)
    with pytest.raises(IntegrityError, match="uq_listings_item_id_channel"):
        add_listing(connection, "channel_a", item_id=item_id)


def test_a_listing_price_must_be_above_zero(connection: Connection) -> None:
    with pytest.raises(IntegrityError, match="ck_listings_price_cents_positive"):
        add_listing(connection, price_cents=0)


def add_flag(connection: Connection, key: str | None, **values: Any) -> None:
    fields = {"event": "flagged", "conflict": "double_sale", "message": "Sold twice."}
    insert(connection, "sync_log", id=uuid4(), conflict_key=key, **(fields | values))


def test_a_flag_needs_a_conflict_and_only_a_flag_has_one(connection: Connection) -> None:
    with (
        pytest.raises(IntegrityError, match="ck_sync_log_flag_has_conflict"),
        connection.begin_nested(),
    ):
        add_flag(connection, None, conflict=None)
    with pytest.raises(IntegrityError, match="ck_sync_log_flag_has_conflict"):
        add_flag(connection, "double_sale:x", event="delisted")


def test_only_a_flag_can_be_resolved(connection: Connection) -> None:
    with pytest.raises(IntegrityError, match="ck_sync_log_only_flags_resolve"):
        insert(
            connection,
            "sync_log",
            id=uuid4(),
            event="delisted",
            message="Came down.",
            resolution="Fine.",
        )


def test_an_open_flag_is_raised_once_and_a_resolved_one_can_come_back(
    connection: Connection,
) -> None:
    add_flag(connection, "stale_listing:channel_a:1")
    with (
        pytest.raises(IntegrityError, match="uq_sync_log_open_conflict_key"),
        connection.begin_nested(),
    ):
        add_flag(connection, "stale_listing:channel_a:1")
    connection.execute(text("UPDATE sync_log SET resolved_at = now(), resolution = 'Ended.'"))
    add_flag(connection, "stale_listing:channel_a:1")


def test_a_channel_order_is_recorded_once(connection: Connection) -> None:
    listing_id = add_listing(connection)
    item_id = connection.execute(
        text("SELECT item_id FROM listings WHERE id = :id"), {"id": listing_id}
    ).scalar_one()
    sale = {
        "item_id": item_id,
        "listing_id": listing_id,
        "channel": "channel_a",
        "channel_order_id": "order-1",
        "price_cents": 2500,
        "sold_at": "2026-11-03 12:00:00+00",
        "source": "webhook",
    }
    insert(connection, "sale_events", id=uuid4(), **sale)
    with pytest.raises(IntegrityError, match="uq_sale_events_channel_channel_order_id"):
        insert(connection, "sale_events", id=uuid4(), **(sale | {"source": "polling"}))


def add_channel_listing(connection: Connection, schema: str) -> UUID:
    listing_id = uuid4()
    insert(
        connection,
        f"{schema}.listings",
        id=listing_id,
        external_ref=str(uuid4()),
        title="Jacket",
        description="A jacket.",
        category="apparel",
        condition="pre_owned",
        price_cents=2500,
        specifics="{}",
    )
    return listing_id


def test_a_channel_sells_each_listing_once(connection: Connection) -> None:
    listing_id = add_channel_listing(connection, "channel_a")
    insert(connection, "channel_a.orders", id=uuid4(), listing_id=listing_id, price_cents=2500)
    with pytest.raises(IntegrityError, match="uq_orders_one_paid_order_per_listing"):
        insert(connection, "channel_a.orders", id=uuid4(), listing_id=listing_id, price_cents=2500)


@pytest.mark.parametrize("schema", CHANNEL_SCHEMAS)
def test_each_channel_role_works_in_its_own_schema(connection: Connection, schema: str) -> None:
    add_channel_listing(connection, schema)
    connection.execute(text(f"SET LOCAL ROLE {schema}"))
    for table in CHANNEL_TABLES:
        connection.execute(text(f"SELECT count(*) FROM {schema}.{table}"))
    assert connection.execute(text(f"SELECT count(*) FROM {schema}.listings")).scalar_one() == 1
    add_channel_listing(connection, schema)


@pytest.mark.parametrize(
    ("schema", "table"),
    [
        ("channel_a", "channel_b.listings"),
        ("channel_b", "channel_a.orders"),
        ("channel_a", "public.items"),
        ("channel_b", "public.listings"),
        ("channel_a", "public.profiles"),
    ],
)
def test_a_channel_role_cannot_reach_another_schema(
    connection: Connection, schema: str, table: str
) -> None:
    connection.execute(text(f"SET LOCAL ROLE {schema}"))
    with pytest.raises(ProgrammingError, match="permission denied"):
        connection.execute(text(f"SELECT count(*) FROM {table}"))


def test_the_web_api_role_cannot_reach_the_channel_schemas(
    connection: Connection, web_api_role: Callable[[], None]
) -> None:
    web_api_role()
    for schema in CHANNEL_SCHEMAS:
        with pytest.raises(ProgrammingError, match="permission denied"), connection.begin_nested():
            connection.execute(text(f"SELECT count(*) FROM {schema}.listings"))


def test_channel_tables_have_row_level_security_for_their_own_role_only(
    connection: Connection,
) -> None:
    rows = connection.execute(
        text(
            "SELECT schemaname, tablename, rowsecurity FROM pg_tables "
            "WHERE schemaname = ANY(:schemas)"
        ),
        {"schemas": CHANNEL_SCHEMAS},
    ).all()
    assert sorted((schema, table) for schema, table, _ in rows) == sorted(
        (schema, table) for schema in CHANNEL_SCHEMAS for table in CHANNEL_TABLES
    )
    assert all(enabled for _, _, enabled in rows)
    policies = connection.execute(
        text("SELECT schemaname, roles FROM pg_policies WHERE schemaname = ANY(:schemas)"),
        {"schemas": CHANNEL_SCHEMAS},
    ).all()
    assert len(policies) == len(CHANNEL_SCHEMAS) * len(CHANNEL_TABLES)
    assert all(roles == [schema] for schema, roles in policies)
