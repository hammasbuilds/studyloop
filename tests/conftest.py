from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from studyloop import ask, db
from studyloop.app import create_app

TINY_BOOK = """# A Small Book of Rivers

## Chapter 1: Water Basics

### What a river is

A river is a natural stream of fresh water that flows toward an ocean, a lake or another river.
The source of a river is the place where it begins, often a spring in the hills.
The mouth of a river is the place where it flows into a larger body of water.
Rivers carry sediment, which is soil and sand picked up from the land along the way.

Sediment settles when the water slows down, and this builds a delta at the mouth of the river.
A delta is a flat area of land shaped like a triangle and made of deposited sediment.
The Nile delta in Egypt covers about 24000 square kilometres of fertile farmland.

### Floods

A flood happens when a river carries more water than its channel can hold.
Heavy rain and melting snow are the two common causes of a flood in spring.
A levee is a raised bank built beside a river to keep the water inside the channel.
Engineers measure the discharge of a river, which is the volume of water passing a point each second.

## Chapter 2: Using Rivers

### Power

A watermill is a machine that uses the flowing water of a river to turn a heavy wheel.
Hydroelectric dams store water in a reservoir and release it through turbines to make electricity.
A turbine is a wheel with curved blades that spins when water pushes against it.
Large dams can change the sediment that reaches the delta downstream and the farmland there.

### Transport

Barges are flat boats that carry heavy cargo along rivers more cheaply than lorries on roads.
A lock is a chamber with gates that raises or lowers boats between two levels of a river.
Canals are artificial channels that join rivers so that boats can travel between them.
"""


@pytest.fixture()
def clock(monkeypatch):
    """A movable clock: ``clock.t`` is the current time, ``clock.advance(days=1)`` moves it."""

    class Clock:
        t = 1_800_000_000.0

        def advance(self, days: float = 0.0, seconds: float = 0.0) -> None:
            self.t += days * 86400 + seconds

    c = Clock()
    monkeypatch.setattr(db, "CLOCK", lambda: c.t)
    return c


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "t.sqlite3"
    db.init(p)
    ask.invalidate()
    return p


@pytest.fixture()
def con(db_path):
    c = db.connect(db_path)
    yield c
    c.close()


@pytest.fixture()
def client(db_path):
    return TestClient(create_app(db_path, sync_import=True))


@pytest.fixture()
def tiny_book(con):
    from studyloop.ingest import Converted, add_book

    return add_book(con, Converted(TINY_BOOK, "A Small Book of Rivers", "markdown", {}))


@pytest.fixture()
def sample_book(con):
    from studyloop.ingest import sample_book

    return sample_book(con)
