"""Shared pytest fixtures for RouteOptimizer.

The optimizer's core functions operate on plain dataclasses (Node, CostMatrix),
so the majority of the suite needs no database, no Flask context, and no network
access. `build_matrix` constructs those dataclasses directly; the `app` fixture
is only used by the handful of tests that exercise database-backed code paths.
"""
from datetime import time

import pytest

from app import create_app
from app.extensions import db as _db
from app.optimizer.engine import CostMatrix, Node


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret-not-used-in-production"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    ORS_API_KEY = None
    FUEL_COST_PER_MILE = 0.65


@pytest.fixture
def app():
    """A Flask app bound to a throwaway in-memory SQLite database."""
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def db(app):
    return _db


def _build_matrix(stop_specs, travel_minutes, depot_loading_minutes=0):
    """Build a CostMatrix by hand, with no database or API involved.

    stop_specs        list of dicts: name, open, close, service, volume
    travel_minutes    (n+1)x(n+1) matrix in MINUTES (index 0 is the depot);
                      converted to the seconds the engine expects
    """
    nodes = [Node(
        index=0, node_type="plant", node_id=1, name="Depot",
        open_time=None, close_time=None,
        service_minutes=depot_loading_minutes, volume_units=0,
    )]
    for i, spec in enumerate(stop_specs, start=1):
        nodes.append(Node(
            index=i, node_type="stop", node_id=i,
            name=spec.get("name", f"Stop {i}"),
            open_time=spec.get("open"), close_time=spec.get("close"),
            service_minutes=spec.get("service", 0),
            volume_units=spec.get("volume", 0),
        ))

    n = len(nodes)
    assert len(travel_minutes) == n, "travel matrix must include the depot row"
    durations = [[travel_minutes[i][j] * 60.0 for j in range(n)] for i in range(n)]
    # Distances are only used for reporting totals; 1 minute -> 1000 m is fine.
    distances = [[travel_minutes[i][j] * 1000.0 for j in range(n)] for i in range(n)]
    return CostMatrix(nodes=nodes, durations=durations, distances=distances)


@pytest.fixture
def build_matrix():
    return _build_matrix


@pytest.fixture
def line_matrix(build_matrix):
    """Four stops on a straight line 1 minute apart, depot at one end.

    Travel cost between any two points is their separation in minutes, so the
    optimal visiting order is unambiguous: 1 -> 2 -> 3 -> 4.
    """
    positions = [0, 1, 2, 3, 4]
    travel = [[abs(a - b) for b in positions] for a in positions]
    specs = [{"name": f"Stop {i}"} for i in range(1, 5)]
    return build_matrix(specs, travel)
