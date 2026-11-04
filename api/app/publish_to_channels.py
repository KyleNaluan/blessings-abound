"""Publish an item to the mock sales channels as a manager, until #42's approval screen does it.

It runs the same code as `POST /items/{id}/listings`, so it needs an item staff said yes to, and
it publishes the newest such item when no item id is given. With docker compose:

    docker compose exec api python -m app.publish_to_channels <manager username> [item id]
"""

import sys
from uuid import UUID

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.channels import Channels, get_channels
from app.db import get_engine
from app.listing_drafts import CHANNEL_NAMES
from app.listings import PublishRequest, publish_listings
from app.models import Decision, DecisionChoice, Item, ItemStatus, Profile, Role


def newest_yes_item(session: Session) -> Item | None:
    """The newest appraised item whose latest decision is a yes."""
    items = session.exec(
        select(Item)
        .where(Item.status == ItemStatus.APPRAISED)
        .order_by(col(Item.updated_at).desc(), col(Item.created_at).desc())
    )
    for item in items:
        latest = session.exec(
            select(Decision)
            .where(Decision.item_id == item.id)
            .order_by(col(Decision.decided_at).desc())
        ).first()
        if latest is not None and latest.decision == DecisionChoice.YES:
            return item
    return None


def publish(session: Session, channels: Channels, arguments: list[str]) -> int:
    if len(arguments) not in (1, 2):
        print(__doc__, file=sys.stderr)
        return 1
    manager = session.exec(select(Profile).where(Profile.username == arguments[0])).first()
    if manager is None or not manager.is_active or manager.role != Role.MANAGER:
        print(f"{arguments[0]} isn't an active manager.", file=sys.stderr)
        return 1
    if len(arguments) == 2:
        item_id = UUID(arguments[1])
    else:
        item = newest_yes_item(session)
        if item is None:
            print("No appraised item has a yes decision yet.", file=sys.stderr)
            return 1
        item_id = item.id
    try:
        listings = publish_listings(session, item_id, PublishRequest(), manager, channels)
    except HTTPException as error:
        print(error.detail, file=sys.stderr)
        return 1
    print(f"Item {item_id}:")
    for listing in listings:
        line = f"  {CHANNEL_NAMES[listing.channel]}: {listing.status.value}"
        if listing.status_detail:
            line += f", {listing.status_detail}"
        print(line)
    return 0


def main() -> int:
    with Session(get_engine()) as session:
        return publish(session, get_channels(), sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
