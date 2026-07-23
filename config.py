"""Application configuration, loaded from environment variables."""
import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-change-me"

    # Default to a local SQLite file; production overrides with DATABASE_URL (Postgres).
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + os.path.join(basedir, "instance", "routeoptimizer.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # External services (wired up in Phase 2 - kept here so the key never lives in code).
    ORS_API_KEY = os.environ.get("ORS_API_KEY")

    # Optimizer / cost defaults (used in Phase 3+).
    FUEL_COST_PER_MILE = float(os.environ.get("FUEL_COST_PER_MILE", "0.65"))
