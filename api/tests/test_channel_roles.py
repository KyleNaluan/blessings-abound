"""The script that lets each mock channel's database role sign in."""

from sqlalchemy import Connection, text

from app.channel_roles import password_variable, set_passwords


def can_sign_in(connection: Connection, role: str) -> bool:
    return connection.execute(
        text("SELECT rolcanlogin FROM pg_roles WHERE rolname = :role"), {"role": role}
    ).scalar_one()


def test_the_password_variable_is_named_after_the_role() -> None:
    assert password_variable("channel_a") == "CHANNEL_A_DB_PASSWORD"


def test_a_role_with_a_password_can_sign_in_and_one_without_is_left_alone(
    connection: Connection,
) -> None:
    connection.execute(text("ALTER ROLE channel_a NOLOGIN"))
    connection.execute(text("ALTER ROLE channel_b NOLOGIN"))

    changed = set_passwords(connection, {"channel_a": "it's a secret", "channel_b": ""})

    assert changed == ["channel_a"]
    assert can_sign_in(connection, "channel_a")
    assert not can_sign_in(connection, "channel_b")


def test_setting_the_same_password_again_is_fine(connection: Connection) -> None:
    for _ in range(2):
        assert set_passwords(connection, {"channel_b": "x"}) == ["channel_b"]
