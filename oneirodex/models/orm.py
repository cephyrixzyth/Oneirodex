"""Framework-independent ORM declarations shared by native and legacy runtimes.

Model classes and table metadata must be importable by FastAPI without loading
Flask. The legacy runtime attaches Flask-SQLAlchemy to the same declarative
base while routes migrate; native runtime code can import mapped models without
initializing that extension.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    MetaData,
    String,
    Table as SQLTable,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.orm import DeclarativeBase, backref, relationship


class _ModelQuery:
    """Retain the legacy ``Model.query`` shorthand while routes are migrating."""

    def __get__(self, _instance, owner):
        from oneirodex.runtime_native.db_session import native_db

        return native_db.session.query(owner)


class ModelBase(DeclarativeBase):
    metadata = MetaData(naming_convention={'ix': 'ix_%(column_0_label)s'})
    query = _ModelQuery()


class _ModelRegistry:
    Model = ModelBase
    metadata = ModelBase.metadata
    BigInteger = BigInteger
    Boolean = Boolean
    Column = Column
    DateTime = DateTime
    Enum = Enum
    Float = Float
    ForeignKey = ForeignKey
    Index = Index
    Integer = Integer
    JSON = JSON
    String = String
    Text = Text
    UniqueConstraint = UniqueConstraint
    text = staticmethod(text)
    backref = staticmethod(backref)
    relationship = staticmethod(relationship)
    false = staticmethod(false)

    @staticmethod
    def Table(name, *columns, **kwargs):
        return SQLTable(name, ModelBase.metadata, *columns, **kwargs)

    @property
    def session(self):
        # Native request scopes must use their explicit SQLAlchemy Session.
        # Outside such a scope, native_db lazily delegates to the legacy
        # extension so existing Flask services keep their scoped-session API.
        from oneirodex.runtime_native.db_session import native_db

        return native_db.session


db = _ModelRegistry()

__all__ = ['ModelBase', 'db']
