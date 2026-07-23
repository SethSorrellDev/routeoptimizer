"""Custom SQLAlchemy column types.

Kept in its own module (no model imports) so Alembic migrations can import it
cheaply without circular-import risk.
"""
from datetime import datetime

from sqlalchemy import String, TypeDecorator


class TimeType(TypeDecorator):
    """Persist datetime.time as 'HH:MM:SS' text; return datetime.time on read.

    SQLite has no native TIME type and rejects datetime.time objects directly.
    """

    impl = String(8)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            parts = value.split(":")
            fmt = "%H:%M" if len(parts) == 2 else "%H:%M:%S"
            value = datetime.strptime(value, fmt).time()
        return value.strftime("%H:%M:%S")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return datetime.strptime(value, "%H:%M:%S").time()
