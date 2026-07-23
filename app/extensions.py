"""Flask extension instances + SQLAlchemy metadata naming convention.

The naming convention forces every index/unique/check/foreign-key/primary-key
constraint to get a deterministic NAME. SQLite batch migrations reject anonymous
constraints, so naming them all up front is what makes future `flask db migrate`
ALTERs work cleanly.
"""
import sqlite3

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_wtf import CSRFProtect
from sqlalchemy import MetaData, event
from sqlalchemy.engine import Engine

naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=naming_convention))
migrate = Migrate()
login_manager = LoginManager()
bcrypt = Bcrypt()
csrf = CSRFProtect()

login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"


@event.listens_for(Engine, "connect")
def _enable_sqlite_fk(dbapi_connection, connection_record):
    """SQLite ignores foreign keys unless this PRAGMA is set per connection.
    Turning it on makes ON DELETE CASCADE behave in dev exactly as it will in
    Postgres production. The isinstance guard keeps it a no-op for Postgres.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
