from collections.abc import Callable, Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine
from sqlmodel import Session, create_engine

from app.settings import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def get_session_factory() -> Callable[[], Session]:
    """New sessions for work that outlives a request, such as a background task."""
    return lambda: Session(get_engine())


SessionFactoryDep = Annotated[Callable[[], Session], Depends(get_session_factory)]
