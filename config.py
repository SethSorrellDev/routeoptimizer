"""Application configuration, loaded from environment variables."""
import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


def _normalize_db_url(url: str) -> str:
    """Render (and most hosts) provide postgresql:// — SQLAlchemy needs the
    +psycopg driver suffix to use psycopg3. Rewrite it if needed.
    """
    if url and url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-change-me"

    _raw_db_url = os.environ.get("DATABASE_URL")
    if _raw_db_url:
        SQLALCHEMY_DATABASE_URI = _normalize_db_url(_raw_db_url)
    else:
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(
            basedir, "instance", "routeoptimizer.db"
        )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # External services (wired up in Phase 2 - kept here so the key never lives in code).
    ORS_API_KEY = os.environ.get("ORS_API_KEY")

    # Optimizer / cost defaults (used in Phase 3+).
    FUEL_COST_PER_MILE = float(os.environ.get("FUEL_COST_PER_MILE", "0.65"))
