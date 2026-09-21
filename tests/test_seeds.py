"""Tests for the seed scripts.

The plant seed is the one that bit us in production: a plant row without
coordinates makes every optimizer run fail with "Distance matrix could not be
built", and the failure only shows up at the point someone clicks Optimize.
"""
import pytest

from app.extensions import db
from app.models import Plant, Role, Route, RouteStop, Stop, User
from seed_demo import seed_demo_route, seed_demo_user
from seed_plant import (
    PLANT_LATITUDE,
    PLANT_LONGITUDE,
    seed_plant,
)
from seed_roles import seed_roles


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
def test_seed_roles_creates_manager_and_ssr(app):
    created = seed_roles()
    assert sorted(created) == ["Manager", "SSR"]
    assert sorted(r.name for r in Role.query.all()) == ["Manager", "SSR"]


def test_seed_roles_is_idempotent(app):
    seed_roles()
    second_run = seed_roles()
    assert second_run == []
    assert Role.query.count() == 2


# ---------------------------------------------------------------------------
# Plant
# ---------------------------------------------------------------------------
def test_seed_plant_sets_coordinates(app):
    """The bug this guards: seeding a plant with no lat/lon."""
    plant, action = seed_plant()
    assert action == "created"
    assert plant.latitude is not None
    assert plant.longitude is not None


def test_seeded_plant_coordinates_are_the_verified_frankfort_location(app):
    plant, _ = seed_plant()
    assert plant.latitude == pytest.approx(PLANT_LATITUDE)
    assert plant.longitude == pytest.approx(PLANT_LONGITUDE)
    # Sanity-check the hemisphere: west-central Indiana, not upstate New York.
    assert 39.0 < plant.latitude < 41.5
    assert -88.0 < plant.longitude < -85.0


def test_seed_plant_backfills_coordinates_on_an_existing_plant(app):
    """Repairs a plant seeded by the older, coordinate-less script."""
    from datetime import time
    db.session.add(Plant(
        name="Legacy plant", address="somewhere",
        latitude=None, longitude=None,
        loading_time_minutes=20,
        shift_start_earliest=time(6, 0),
        max_shift_minutes=600,
    ))
    db.session.commit()

    plant, action = seed_plant()
    assert action == "backfilled coordinates"
    assert plant.latitude == pytest.approx(PLANT_LATITUDE)


def test_seed_plant_leaves_a_complete_plant_alone(app):
    seed_plant()
    plant = Plant.query.first()
    plant.latitude = 40.0
    plant.longitude = -86.0
    db.session.commit()

    _, action = seed_plant()
    assert action == "unchanged"
    assert Plant.query.first().latitude == pytest.approx(40.0)


def test_seed_plant_does_not_create_a_second_plant(app):
    seed_plant()
    seed_plant()
    assert Plant.query.count() == 1


def test_seeded_plant_has_a_usable_shift_configuration(app):
    plant, _ = seed_plant()
    assert plant.max_shift_minutes > 0
    assert plant.loading_time_minutes >= 0
    assert plant.shift_start_earliest is not None


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------
def test_seed_demo_route_requires_a_plant(app):
    with pytest.raises(RuntimeError, match="seed_plant"):
        seed_demo_route()


def test_seed_demo_route_creates_a_route_with_stops(app):
    seed_plant()
    route, created = seed_demo_route()
    assert route.name == "Route 64"
    assert len(created) == 5
    assert len(route.route_stops) == 5


def test_seed_demo_route_is_idempotent(app):
    seed_plant()
    seed_demo_route()
    route, created = seed_demo_route()
    assert created == []
    assert Route.query.count() == 1
    assert Stop.query.count() == 5
    assert RouteStop.query.count() == 5


def test_demo_stops_all_have_a_service_window_and_volume(app):
    seed_plant()
    seed_demo_route()
    for stop in Stop.query.all():
        assert stop.open_time is not None, stop.name
        assert stop.close_time is not None, stop.name
        assert stop.service_time_solo_minutes > 0, stop.name
        assert stop.volume_units > 0, stop.name


def test_demo_route_volume_fits_the_truck(app):
    """A demo that opens on a capacity violation is a bad first impression."""
    seed_plant()
    route, _ = seed_demo_route()
    total = sum(rs.stop.volume_units for rs in route.route_stops)
    assert total <= route.truck_capacity_volume


def test_demo_stops_are_seeded_without_invented_coordinates(app):
    """Coordinates come from geocoding or a human, never from this script."""
    seed_plant()
    seed_demo_route()
    assert all(s.latitude is None and s.longitude is None for s in Stop.query.all())


# ---------------------------------------------------------------------------
# Demo login
# ---------------------------------------------------------------------------
def test_seed_demo_user_creates_a_manager_with_a_working_password(app):
    seed_roles()
    user, created = seed_demo_user("demo", "a-test-password")
    assert created is True
    assert user.is_manager is True
    assert user.check_password("a-test-password") is True
    assert user.check_password("wrong") is False


def test_seed_demo_user_does_not_store_the_password_in_plain_text(app):
    seed_roles()
    user, _ = seed_demo_user("demo", "a-test-password")
    assert "a-test-password" not in user.password_hash


def test_seed_demo_user_is_idempotent(app):
    seed_roles()
    seed_demo_user("demo", "a-test-password")
    _, created = seed_demo_user("demo", "a-different-password")
    assert created is False
    assert User.query.count() == 1


def test_seed_demo_user_requires_roles_to_exist(app):
    with pytest.raises(RuntimeError, match="seed_roles"):
        seed_demo_user("demo", "a-test-password")
