"""Base SQLAlchemy model class."""

from sqlalchemy import MetaData, inspect
from sqlalchemy.orm import DeclarativeBase

from app.services.secret_redaction import redact_value

# SQLAlchemy naming convention for constraints
# This ensures all constraints have deterministic, predictable names
naming_convention = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(referred_table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all models."""

    metadata = MetaData(naming_convention=naming_convention)


def redact_loaded(target: Base, fields: tuple[str, ...]) -> None:
    """Apply the secret floor to loaded columns in a flush listener; assigns only on a match."""
    loaded = inspect(target).dict  # unloaded columns are not being written
    for attr in fields:
        if attr in loaded:
            value = loaded[attr]
            redacted = redact_value(value)  # same object when nothing matched
            if redacted is not value:
                setattr(target, attr, redacted)
