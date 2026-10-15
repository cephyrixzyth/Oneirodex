from __future__ import annotations

from sqlalchemy import Integer, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from oneirodex.utils.browse_query import _native_paginate


class Base(DeclarativeBase):
    pass


class Row(Base):
    __tablename__ = 'native_browse_page_rows'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)


def test_native_pagination_preserves_total_page_count_and_order_without_flask():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(Row(id=value) for value in range(1, 6))
        session.commit()

        items, total, pages = _native_paginate(
            select(Row).order_by(Row.id), page=2, per_page=2, session=session,
        )

    assert [row.id for row in items] == [3, 4]
    assert (total, pages) == (5, 3)
    engine.dispose()


def test_native_pagination_matches_flask_non_error_fallbacks():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Row(id=1))
        session.commit()

        items, total, pages = _native_paginate(
            select(Row), page=-5, per_page=0, session=session,
        )

    assert [row.id for row in items] == [1]
    assert (total, pages) == (1, 1)
    engine.dispose()
