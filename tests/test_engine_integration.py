"""Database-backed tests for matrix assembly and the full optimize() pipeline.

These use an in-memory SQLite database seeded by hand. No OpenRouteService
calls are made — every travel time is written straight into the cache table,
which is exactly how the optimizer reads them in production.
"""
from datetime import time

import pytest

from app.extensions import db
from app.models import (
    DistanceMatrixEntry,
    Plant,
    Route,
    RouteStop,
    Stop,
)
from app.optimizer.engine import cost_matrix_from_cache, optimize


def _cache(origin_type, origin_id, dest_type, dest_id, minutes):
    db.session.add(DistanceMatrixEntry(
        origin_type=origin_type, origin_id=origin_id,
        dest_type=dest_type, dest_id=dest_id,
        distance_meters=minutes * 1000.0,
        duration_seconds=minutes * 60.0,
    ))


def seed(stop_specs, travel_minutes, service_days="MTWRF",
         shift_start=time(6, 0), loading=20, max_shift=900, capacity=200,
         plant_has_coords=True):
    """Seed a plant, a route and its stops, plus a fully populated matrix cache."""
    plant = Plant(
        name="Cintas Uniform Services",
        address="3470 W County Rd 0 N/S, Frankfort, IN 46041",
        latitude=40.287528634526396 if plant_has_coords else None,
        longitude=-86.57083716973595 if plant_has_coords else None,
        loading_time_minutes=loading,
        shift_start_earliest=shift_start,
        max_shift_minutes=max_shift,
    )
    db.session.add(plant)
    db.session.flush()

    route = Route(name="Route 64", plant_id=plant.id, truck_capacity_volume=capacity)
    db.session.add(route)
    db.session.flush()

    stops = []
    for spec in stop_specs:
        stop = Stop(
            plant_id=plant.id,
            name=spec["name"],
            address=f"{spec['name']}, Kokomo, IN",
            latitude=spec.get("lat", 40.46),
            longitude=spec.get("lon", -86.13),
            service_time_solo_minutes=spec.get("service", 15),
            open_time=spec.get("open"),
            close_time=spec.get("close"),
            volume_units=spec.get("volume", 10),
        )
        db.session.add(stop)
        db.session.flush()
        stops.append(stop)
        db.session.add(RouteStop(
            route_id=route.id, stop_id=stop.id,
            service_days=spec.get("days", service_days),
            volume_override=spec.get("volume_override"),
        ))
    db.session.flush()

    ids = [("plant", plant.id)] + [("stop", s.id) for s in stops]
    for i, (otype, oid) in enumerate(ids):
        for j, (dtype, did) in enumerate(ids):
            if i == j:
                continue
            _cache(otype, oid, dtype, did, travel_minutes[i][j])

    db.session.commit()
    return plant, route, stops


# ---------------------------------------------------------------------------
# cost_matrix_from_cache — the guard conditions
# ---------------------------------------------------------------------------
def test_matrix_is_none_for_an_unknown_route(app):
    assert cost_matrix_from_cache(999, "W") is None


def test_matrix_is_none_when_the_plant_has_no_coordinates(app):
    """Regression guard: seed_plant.py originally left lat/lon unset, which
    surfaced in production as 'Distance matrix could not be built'."""
    _, route, _ = seed(
        [{"name": "Starbucks"}], [[0, 30], [30, 0]], plant_has_coords=False,
    )
    assert cost_matrix_from_cache(route.id, "W") is None


def test_matrix_is_none_when_a_stop_has_no_coordinates(app):
    _, route, stops = seed([{"name": "Meijer"}], [[0, 30], [30, 0]])
    stops[0].latitude = None
    db.session.commit()
    assert cost_matrix_from_cache(route.id, "W") is None


def test_matrix_is_none_when_no_stop_runs_on_the_requested_day(app):
    _, route, _ = seed(
        [{"name": "Chipotle", "days": "WF"}], [[0, 30], [30, 0]],
    )
    assert cost_matrix_from_cache(route.id, "T") is None
    assert cost_matrix_from_cache(route.id, "W") is not None


def test_matrix_is_none_when_a_cached_pair_is_missing(app):
    _, route, stops = seed([{"name": "Meijer"}], [[0, 30], [30, 0]])
    DistanceMatrixEntry.query.filter_by(
        origin_type="stop", origin_id=stops[0].id
    ).delete()
    db.session.commit()
    assert cost_matrix_from_cache(route.id, "W") is None


# ---------------------------------------------------------------------------
# cost_matrix_from_cache — the happy path
# ---------------------------------------------------------------------------
def test_matrix_puts_the_depot_first_and_then_the_stops(app):
    _, route, _ = seed(
        [{"name": "Starbucks"}, {"name": "Meijer"}],
        [[0, 30, 40], [30, 0, 10], [40, 10, 0]],
    )
    matrix = cost_matrix_from_cache(route.id, "W")
    assert matrix.n == 3
    assert matrix.nodes[0].node_type == "plant"
    assert [n.node_type for n in matrix.nodes[1:]] == ["stop", "stop"]


def test_matrix_reads_travel_times_from_the_cache_in_seconds(app):
    _, route, _ = seed([{"name": "Starbucks"}], [[0, 30], [30, 0]])
    matrix = cost_matrix_from_cache(route.id, "W")
    assert matrix.durations[0][1] == 30 * 60
    assert matrix.durations[1][1] == 0


def test_matrix_uses_the_route_level_volume_override(app):
    _, route, _ = seed(
        [{"name": "Meijer", "volume": 25, "volume_override": 55}],
        [[0, 30], [30, 0]],
    )
    matrix = cost_matrix_from_cache(route.id, "W")
    assert matrix.nodes[1].volume_units == 55


def test_matrix_falls_back_to_the_stop_volume_without_an_override(app):
    _, route, _ = seed(
        [{"name": "Meijer", "volume": 25}], [[0, 30], [30, 0]],
    )
    matrix = cost_matrix_from_cache(route.id, "W")
    assert matrix.nodes[1].volume_units == 25


def test_matrix_includes_only_the_stops_running_that_day(app):
    _, route, _ = seed(
        [{"name": "Wednesday only", "days": "W"},
         {"name": "Tuesday only", "days": "T"}],
        [[0, 30, 40], [30, 0, 10], [40, 10, 0]],
    )
    matrix = cost_matrix_from_cache(route.id, "W")
    assert [n.name for n in matrix.nodes[1:]] == ["Wednesday only"]


# ---------------------------------------------------------------------------
# optimize()
# ---------------------------------------------------------------------------
def test_optimize_returns_none_for_an_unknown_route(app):
    assert optimize(999, "W") is None


def test_optimize_sequences_every_stop_exactly_once(app):
    _, route, _ = seed(
        [{"name": "A"}, {"name": "B"}, {"name": "C"}],
        [[0, 10, 20, 30], [10, 0, 10, 20], [20, 10, 0, 10], [30, 20, 10, 0]],
    )
    plan = optimize(route.id, "W")
    assert sorted(plan.order) == [1, 2, 3]
    assert [r.sequence for r in plan.stop_results] == [1, 2, 3]


def test_optimize_return_time_is_never_before_the_last_stop_departure(app):
    """Regression test for the wait-time bug.

    estimated_return was computed by re-summing drive + service time, which
    silently dropped the hours a truck spends waiting for a late-opening
    customer. The dashboard could therefore show a return time EARLIER than
    the truck's departure from its final stop.
    """
    _, route, _ = seed(
        [{"name": "Early customer", "open": time(6, 0), "close": time(20, 0),
          "service": 15},
         {"name": "Opens at 3pm", "open": time(15, 0), "close": time(21, 0),
          "service": 15}],
        [[0, 30, 40], [30, 0, 30], [40, 30, 0]],
    )
    plan = optimize(route.id, "W")

    last_departure = plan.stop_results[-1].depart_minutes
    assert plan.estimated_return_minutes >= last_departure, (
        f"return {plan.estimated_return_minutes:.0f} is before the last stop's "
        f"departure {last_departure:.0f} — wait time was dropped"
    )


def test_optimize_return_time_accounts_for_the_drive_home(app):
    _, route, _ = seed(
        [{"name": "Only stop", "open": time(6, 0), "close": time(20, 0),
          "service": 15}],
        [[0, 30], [30, 0]],
    )
    plan = optimize(route.id, "W")
    last_departure = plan.stop_results[-1].depart_minutes
    assert plan.estimated_return_minutes == pytest.approx(last_departure + 30)


def test_optimize_flags_a_violated_time_window_with_a_warning(app):
    _, route, _ = seed(
        [{"name": "Closes early", "open": time(6, 0), "close": time(6, 30),
          "service": 15}],
        [[0, 240], [240, 0]],  # four hours away; cannot arrive before 06:30
    )
    plan = optimize(route.id, "W")
    assert any(not r.time_window_ok for r in plan.stop_results)
    assert any("infeasible window" in w for w in plan.warnings)


def test_optimize_reports_capacity_utilisation_as_a_percentage(app):
    _, route, _ = seed(
        [{"name": "A", "volume": 60}, {"name": "B", "volume": 40}],
        [[0, 10, 20], [10, 0, 10], [20, 10, 0]],
        capacity=200,
    )
    plan = optimize(route.id, "W")
    assert plan.capacity_utilization_pct == pytest.approx(50.0)


def test_optimize_marks_an_over_capacity_route_infeasible(app):
    _, route, _ = seed(
        [{"name": "Too much", "volume": 500}], [[0, 20], [20, 0]], capacity=200,
    )
    plan = optimize(route.id, "W")
    assert plan.feasible is False
    assert any("maximum assistants" in w for w in plan.warnings)


def test_optimize_needs_no_assistants_for_a_comfortable_route(app):
    _, route, _ = seed(
        [{"name": "Easy", "service": 15, "volume": 10}], [[0, 20], [20, 0]],
    )
    plan = optimize(route.id, "W")
    assert plan.feasible is True
    assert plan.assistants == 0


def test_optimize_totals_include_the_return_leg(app):
    _, route, _ = seed([{"name": "Solo"}], [[0, 30], [30, 0]])
    plan = optimize(route.id, "W")
    # Out and back: 30 minutes each way.
    assert plan.total_drive_seconds == pytest.approx(2 * 30 * 60)
    assert plan.total_distance_m == pytest.approx(2 * 30 * 1000)
