"""Smoke tests for application wiring and configuration.

create_app() raises on a duplicate endpoint name, so simply constructing the
app catches a whole class of blueprint registration mistakes — including the
"View function mapping is overwriting an existing endpoint function" error
that a double-applied patch once produced.
"""
from config import _normalize_db_url


def test_create_app_registers_every_blueprint_without_collisions(app):
    endpoints = [rule.endpoint for rule in app.url_map.iter_rules()]
    assert len(endpoints) == len(set(endpoints)), "duplicate endpoint registered"


def test_expected_blueprints_are_present(app):
    prefixes = {e.split(".")[0] for e in
                (rule.endpoint for rule in app.url_map.iter_rules())}
    for blueprint in ("main", "auth", "manager", "ssr", "optimizer"):
        assert blueprint in prefixes, f"{blueprint} blueprint not registered"


def test_secret_key_is_configured(app):
    assert app.config["SECRET_KEY"]


def test_sqlalchemy_modification_tracking_is_disabled(app):
    """Leaving this on costs memory and does nothing for this app."""
    assert app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] is False


# ---------------------------------------------------------------------------
# DATABASE_URL normalisation
# ---------------------------------------------------------------------------
def test_postgres_url_gets_the_psycopg_driver_suffix():
    """Render hands out postgresql://; SQLAlchemy needs +psycopg for psycopg3."""
    result = _normalize_db_url("postgresql://user:pw@host:5432/db")
    assert result == "postgresql+psycopg://user:pw@host:5432/db"


def test_an_already_qualified_postgres_url_is_left_alone():
    url = "postgresql+psycopg://user:pw@host:5432/db"
    assert _normalize_db_url(url) == url


def test_only_the_scheme_is_rewritten():
    """A password or database name containing the scheme must not be mangled."""
    url = "postgresql://user:postgresql://@host:5432/db"
    assert _normalize_db_url(url).count("postgresql+psycopg://") == 1


def test_sqlite_urls_are_untouched():
    url = "sqlite:///instance/routeoptimizer.db"
    assert _normalize_db_url(url) == url


def test_empty_database_url_is_passed_through():
    assert _normalize_db_url("") == ""
    assert _normalize_db_url(None) is None
