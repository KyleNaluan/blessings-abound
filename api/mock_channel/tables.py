"""The tables each mock channel keeps in its own schema, `channel_a` or `channel_b`.

Both schemas have the same tables. The design and the reasons behind it are in docs/database.md.
"""

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

SCHEMAS = ("channel_a", "channel_b")
LISTING_STATUSES = ("active", "sold", "ended")
ORDER_STATUSES = ("paid", "cancelled")

metadata = sa.MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _time(name: str, *, nullable: bool = False) -> sa.Column[datetime]:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


@dataclass(frozen=True)
class ChannelTables:
    listings: sa.Table
    orders: sa.Table
    controls: sa.Table


def _tables(schema: str) -> ChannelTables:
    listings = sa.Table(
        "listings",
        metadata,
        sa.Column("id", sa.Uuid, primary_key=True),
        # The seller's own id for the listing, which makes a repeated publish return the same one.
        sa.Column("external_ref", sa.Text, nullable=False, unique=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("condition", sa.Text, nullable=False),
        sa.Column("price_cents", sa.Integer, nullable=False),
        sa.Column("brand", sa.Text),
        sa.Column("size", sa.Text),
        sa.Column("color", sa.Text),
        sa.Column("specifics", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        _time("created_at"),
        _time("updated_at"),
        _time("ended_at", nullable=True),
        sa.CheckConstraint("price_cents > 0", name="price_cents_positive"),
        sa.CheckConstraint(_one_of("status", LISTING_STATUSES), name="status"),
        schema=schema,
    )
    orders = sa.Table(
        "orders",
        metadata,
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column(
            "listing_id",
            sa.Uuid,
            sa.ForeignKey(f"{schema}.listings.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("price_cents", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="paid"),
        _time("created_at"),
        # Set once the seller's app has the order, by a webhook answered 2xx or an acknowledgment.
        _time("acknowledged_at", nullable=True),
        sa.CheckConstraint("price_cents > 0", name="price_cents_positive"),
        sa.CheckConstraint(_one_of("status", ORDER_STATUSES), name="status"),
        # A channel sells each listing once, so a double sale can only happen across channels.
        sa.Index(
            "uq_orders_one_paid_order_per_listing",
            "listing_id",
            unique=True,
            postgresql_where=sa.text("status = 'paid'"),
        ),
        schema=schema,
    )
    controls = sa.Table(
        "controls",
        metadata,
        # A single row, so the switch holds for every process of the service.
        sa.Column("id", sa.Boolean, primary_key=True, server_default=sa.true()),
        # The demo switch that makes the channel act as if it were down.
        sa.Column("offline", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.CheckConstraint("id", name="single_row"),
        schema=schema,
    )
    return ChannelTables(listings=listings, orders=orders, controls=controls)


TABLES = {schema: _tables(schema) for schema in SCHEMAS}
