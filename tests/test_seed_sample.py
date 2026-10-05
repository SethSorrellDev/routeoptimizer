"""Tests for the fictional sample data set."""
import pytest

from app.extensions import db
from app.models import (
    DistanceMatrixEntry, Route, RouteStop, Stop, StopContact,
)
from app.optimizer.engine import cost_matrix_from_cache, optimize
from seed_plant import seed_plant
from seed_sample import (
    ROUTE_A, ROUTE_B, TRUCK_CAPACITY, remove_sample, seed_sample,
)


@pytest.fixture
def seeded(app):
    seed_plant()
    seed_sample()
    return app


def test_requires_a_plant_with_coordinates(app):
    with pytest.raises(RuntimeError, match="seed_plant"):
        seed_sample()


def test_creates_two_routes_and_fourteen_stops(seeded):
    assert Route.query.count() == 2
    assert Stop.query.count() == 14
    assert Route.query.filter_by(name=ROUTE_A).one().route_stops.__len__() == 8
    assert Route.query.filter_by(name=ROUTE_B).one().route_stops.__len__() == 7


def test_is_idempotent(seeded):
    second = seed_sample()
    assert second == {"routes": 0, "stops": 0, "links": 0,
                      "matrix_entries": 0, "closures": 0}
    assert Stop.query.count() == 14
    assert RouteStop.query.count() == 15


def test_every_stop_has_coordinates_window_and_a_contact(seeded):
    for s in Stop.query.all():
        assert s.latitude and s.longitude, s.name
        assert s.open_time < s.close_time, s.name
        assert len(s.contacts) == 1, s.name


def test_nothing_resembles_real_data(seeded):
    for c in StopContact.query.all():
        assert c.phone.startswith("555-01"), c.phone
    for s in Stop.query.all():
        assert s.address.endswith(("46000", "46001", "46002", "46010", "46011")), s.address


def test_stops_are_scattered_near_the_plant(seeded):
    from seed_plant import PLANT_LATITUDE, PLANT_LONGITUDE
    for s in Stop.query.all():
        assert abs(s.latitude - PLANT_LATITUDE) < 0.3
        assert abs(s.longitude - PLANT_LONGITUDE) < 0.3


def test_cache_is_complete_and_asymmetric(seeded):
    n_nodes = 15  # plant + 14 stops
    assert DistanceMatrixEntry.query.count() == n_nodes * (n_nodes - 1)
    a = DistanceMatrixEntry.query.filter_by(
        origin_type="plant", dest_type="stop", dest_id=1).one()
    b = DistanceMatrixEntry.query.filter_by(
        origin_type="stop", origin_id=1, dest_type="plant").one()
    assert a.duration_seconds != b.duration_seconds


@pytest.mark.parametrize("name,day", [(ROUTE_A, "M"), (ROUTE_A, "F"), (ROUTE_B, "T"), (ROUTE_B, "R")])
def test_the_optimizer_can_run_every_route_day_with_no_network(seeded, name, day):
    route = Route.query.filter_by(name=name).one()
    assert cost_matrix_from_cache(route.id, day) is not None
    assert optimize(route.id, day) is not None


def test_route_a_is_feasible_and_fits_the_truck(seeded):
    route = Route.query.filter_by(name=ROUTE_A).one()
    plan = optimize(route.id, "M")
    assert plan.feasible is True
    assert plan.warnings == []
    assert plan.capacity_utilization_pct <= 100
    assert sum(rs.stop.volume_units for rs in route.route_stops) <= TRUCK_CAPACITY


def test_route_b_demonstrates_window_warnings(seeded):
    route = Route.query.filter_by(name=ROUTE_B).one()
    plan = optimize(route.id, "T")
    assert plan.warnings, "Route B is meant to produce a window warning"


def test_shared_stop_runs_on_both_routes_on_different_days(seeded):
    stop = Stop.query.filter_by(name="Maple Court Apartments").one()
    days = {rs.route.name: rs.service_days for rs in stop.route_stops}
    assert days == {ROUTE_A: "MWF", ROUTE_B: "TR"}


def test_remove_deletes_only_sample_data(seeded):
    from app.models import Plant
    plant = Plant.query.first()
    keep = Stop(plant_id=plant.id, name="Keep me", latitude=40.3, longitude=-86.5,
                service_time_solo_minutes=5, volume_units=1)
    db.session.add(keep)
    db.session.commit()

    counts = remove_sample()
    assert counts["routes"] == 2 and counts["stops"] == 14
    assert Route.query.count() == 0
    assert [s.name for s in Stop.query.all()] == ["Keep me"]
    assert DistanceMatrixEntry.query.count() == 0
    assert Plant.query.count() == 1


def test_remove_is_safe_to_repeat_and_reseed_works(seeded):
    remove_sample()
    remove_sample()
    seed_sample()
    assert Stop.query.count() == 14
