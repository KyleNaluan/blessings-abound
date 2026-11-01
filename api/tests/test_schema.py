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
    "alembic_version",
]
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
    assert len(columns) == 4
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
    signed = {
        column
        for _, column, _ in columns_named(connection, "%\\_cents")
        if not connection.execute(
            text("SELECT 1 FROM pg_constraint WHERE contype = 'c' AND conname = :name"),
            {"name": f"ck_appraisals_{column}_non_negative"},
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
    assert len(columns) == 9
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
