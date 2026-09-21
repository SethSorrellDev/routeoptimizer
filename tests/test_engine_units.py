"""Unit tests for the VRPTW heuristics.

These exercise the solver's arithmetic directly, with no database, no Flask
context and no OpenRouteService calls.
"""
from datetime import time

import pytest

from app.optimizer.engine import (
    _is_feasible,
    _productivity_factor,
    _route_duration,
    _time_to_minutes,
    assistants_needed,
    evaluate_route,
    nearest_neighbor,
    recommend_departure,
    two_opt,
)

BIG_CAPACITY = 10_000
LONG_SHIFT = 10_000


# ---------------------------------------------------------------------------
# Time conversion
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value,expected", [
    (time(0, 0), 0),
    (time(6, 30), 390),
    (time(12, 0), 720),
    (time(23, 59), 1439),
])
def test_time_to_minutes_converts_clock_time(value, expected):
    assert _time_to_minutes(value) == expected


def test_time_to_minutes_includes_seconds_as_a_fraction():
    assert _time_to_minutes(time(6, 0, 30)) == 360.5


# ---------------------------------------------------------------------------
# Feasibility: time windows
# ---------------------------------------------------------------------------
def test_feasible_when_arrival_is_inside_the_time_window(build_matrix):
    matrix = build_matrix(
        [{"open": time(8, 0), "close": time(17, 0), "service": 15}],
        [[0, 30], [30, 0]],
    )
    # Depart 08:00 (480), arrive 08:30 — comfortably inside 08:00-17:00.
    assert _is_feasible([1], matrix, 480, LONG_SHIFT, BIG_CAPACITY) is True


def test_infeasible_when_arrival_is_after_close_time(build_matrix):
    matrix = build_matrix(
        [{"open": time(8, 0), "close": time(10, 0), "service": 15}],
        [[0, 30], [30, 0]],
    )
    # Depart 10:00 (600), arrive 10:30 — after the 10:00 close.
    assert _is_feasible([1], matrix, 600, LONG_SHIFT, BIG_CAPACITY) is False


def test_arriving_before_open_is_feasible_because_the_truck_waits(build_matrix):
    matrix = build_matrix(
        [{"open": time(15, 0), "close": time(21, 0), "service": 15}],
        [[0, 30], [30, 0]],
    )
    # Arrives 06:30, waits until 15:00. Early arrival is not a violation.
    assert _is_feasible([1], matrix, 360, LONG_SHIFT, BIG_CAPACITY) is True


def test_a_stop_with_no_window_is_always_time_feasible(build_matrix):
    matrix = build_matrix([{"service": 15}], [[0, 30], [30, 0]])
    assert _is_feasible([1], matrix, 1200, LONG_SHIFT, BIG_CAPACITY) is True


# ---------------------------------------------------------------------------
# Feasibility: capacity
# ---------------------------------------------------------------------------
def test_infeasible_when_cumulative_volume_exceeds_truck_capacity(build_matrix):
    matrix = build_matrix(
        [{"volume": 120}, {"volume": 100}],
        [[0, 10, 10], [10, 0, 10], [10, 10, 0]],
    )
    assert _is_feasible([1, 2], matrix, 360, LONG_SHIFT, 200) is False


def test_feasible_when_cumulative_volume_exactly_equals_capacity(build_matrix):
    matrix = build_matrix(
        [{"volume": 120}, {"volume": 80}],
        [[0, 10, 10], [10, 0, 10], [10, 10, 0]],
    )
    assert _is_feasible([1, 2], matrix, 360, LONG_SHIFT, 200) is True


def test_capacity_is_cumulative_not_per_stop(build_matrix):
    """No single stop exceeds capacity, but together they do."""
    matrix = build_matrix(
        [{"volume": 60}, {"volume": 60}, {"volume": 60}],
        [[0, 5, 5, 5], [5, 0, 5, 5], [5, 5, 0, 5], [5, 5, 5, 0]],
    )
    assert _is_feasible([1, 2], matrix, 360, LONG_SHIFT, 150) is True
    assert _is_feasible([1, 2, 3], matrix, 360, LONG_SHIFT, 150) is False


# ---------------------------------------------------------------------------
# Feasibility: shift length
# ---------------------------------------------------------------------------
def test_infeasible_when_the_round_trip_exceeds_max_shift(build_matrix):
    matrix = build_matrix(
        [{"service": 60}],
        [[0, 180], [180, 0]],
    )
    # 180 out + 60 service + 180 back = 420 minutes against a 300-minute shift.
    assert _is_feasible([1], matrix, 360, 300, BIG_CAPACITY) is False
    assert _is_feasible([1], matrix, 360, 480, BIG_CAPACITY) is True


def test_shift_length_accounts_for_the_return_leg(build_matrix):
    """A route that fits on the way out can still bust the shift coming home."""
    matrix = build_matrix([{"service": 0}], [[0, 100], [100, 0]])
    assert _is_feasible([1], matrix, 0, 150, BIG_CAPACITY) is False
    assert _is_feasible([1], matrix, 0, 200, BIG_CAPACITY) is True


# ---------------------------------------------------------------------------
# Nearest-neighbour construction
# ---------------------------------------------------------------------------
def test_nearest_neighbor_visits_every_stop_exactly_once(line_matrix):
    order = nearest_neighbor(line_matrix, 360)
    assert sorted(order) == [1, 2, 3, 4]
    assert len(order) == len(set(order))


def test_nearest_neighbor_prefers_the_closer_stop_first(build_matrix):
    matrix = build_matrix(
        [{"name": "Far"}, {"name": "Near"}],
        [[0, 90, 10], [90, 0, 80], [10, 80, 0]],
    )
    order = nearest_neighbor(matrix, 360)
    assert order[0] == 2, "should visit the 10-minute stop before the 90-minute one"


def test_nearest_neighbor_still_returns_all_stops_when_one_is_unreachable(build_matrix):
    """An unreachable stop is appended rather than silently dropped."""
    matrix = build_matrix(
        [{"name": "Open", "close": time(23, 0)},
         {"name": "Already closed", "close": time(6, 0)}],
        [[0, 10, 10], [10, 0, 10], [10, 10, 0]],
    )
    order = nearest_neighbor(matrix, 600)  # 10:00, well after the 06:00 close
    assert sorted(order) == [1, 2]


# ---------------------------------------------------------------------------
# 2-opt local search
# ---------------------------------------------------------------------------
def test_two_opt_improves_a_deliberately_crossed_route(line_matrix):
    crossed = [1, 3, 2, 4]
    before = _route_duration(crossed, line_matrix, 0)
    improved = two_opt(crossed, line_matrix, 0, LONG_SHIFT, BIG_CAPACITY)
    after = _route_duration(improved, line_matrix, 0)
    assert after < before
    assert improved == [1, 2, 3, 4]


def test_two_opt_never_returns_a_worse_route_than_it_was_given(line_matrix):
    for order in ([1, 2, 3, 4], [4, 3, 2, 1], [2, 4, 1, 3], [1, 3, 2, 4]):
        before = _route_duration(order, line_matrix, 0)
        after = _route_duration(
            two_opt(order, line_matrix, 0, LONG_SHIFT, BIG_CAPACITY),
            line_matrix, 0,
        )
        assert after <= before + 1e-9


def test_two_opt_preserves_the_set_of_stops(line_matrix):
    result = two_opt([2, 4, 1, 3], line_matrix, 0, LONG_SHIFT, BIG_CAPACITY)
    assert sorted(result) == [1, 2, 3, 4]


def test_two_opt_keeps_a_feasible_route_feasible(build_matrix):
    """Reversals are only accepted if they survive the constraint check."""
    matrix = build_matrix(
        [{"name": "A", "open": time(8, 0), "close": time(9, 0), "service": 10},
         {"name": "B", "open": time(9, 0), "close": time(12, 0), "service": 10},
         {"name": "C", "open": time(10, 0), "close": time(16, 0), "service": 10}],
        [[0, 20, 25, 30], [20, 0, 15, 20], [25, 15, 0, 15], [30, 20, 15, 0]],
    )
    start = [1, 2, 3]
    assert _is_feasible(start, matrix, 460, LONG_SHIFT, BIG_CAPACITY)
    result = two_opt(start, matrix, 460, LONG_SHIFT, BIG_CAPACITY)
    assert _is_feasible(result, matrix, 460, LONG_SHIFT, BIG_CAPACITY)


def test_two_opt_respects_capacity_while_reordering(line_matrix):
    result = two_opt([1, 3, 2, 4], line_matrix, 0, LONG_SHIFT, BIG_CAPACITY)
    assert _is_feasible(result, line_matrix, 0, LONG_SHIFT, BIG_CAPACITY)


# ---------------------------------------------------------------------------
# Per-stop evaluation
# ---------------------------------------------------------------------------
def test_evaluate_route_records_wait_time_when_arriving_before_open(build_matrix):
    matrix = build_matrix(
        [{"open": time(9, 0), "close": time(17, 0), "service": 15}],
        [[0, 30], [30, 0]],
    )
    results = evaluate_route([1], matrix, 480)  # depart 08:00, arrive 08:30
    assert results[0].arrive_minutes == 510          # 08:30
    assert results[0].wait_minutes == 30             # waits until 09:00
    assert results[0].start_service_minutes == 540   # 09:00
    assert results[0].depart_minutes == 555          # 09:15


def test_evaluate_route_reports_no_wait_when_the_stop_is_already_open(build_matrix):
    matrix = build_matrix(
        [{"open": time(6, 0), "close": time(17, 0), "service": 15}],
        [[0, 30], [30, 0]],
    )
    results = evaluate_route([1], matrix, 480)
    assert results[0].wait_minutes == 0
    assert results[0].start_service_minutes == results[0].arrive_minutes


def test_evaluate_route_flags_a_violated_time_window(build_matrix):
    matrix = build_matrix(
        [{"open": time(8, 0), "close": time(9, 0), "service": 15}],
        [[0, 30], [30, 0]],
    )
    ok = evaluate_route([1], matrix, 480)      # arrive 08:30 — inside
    late = evaluate_route([1], matrix, 600)    # arrive 10:30 — after close
    assert ok[0].time_window_ok is True
    assert late[0].time_window_ok is False


def test_evaluate_route_accumulates_volume_across_stops(build_matrix):
    matrix = build_matrix(
        [{"volume": 30}, {"volume": 25}, {"volume": 12}],
        [[0, 5, 5, 5], [5, 0, 5, 5], [5, 5, 0, 5], [5, 5, 5, 0]],
    )
    results = evaluate_route([1, 2, 3], matrix, 360)
    assert [r.cumulative_volume for r in results] == [30, 55, 67]


def test_evaluate_route_numbers_stops_from_one(line_matrix):
    results = evaluate_route([1, 2, 3, 4], line_matrix, 360)
    assert [r.sequence for r in results] == [1, 2, 3, 4]


def test_evaluate_route_departure_is_never_before_arrival(build_matrix):
    """Guards the wait-time accounting that the return-time bug got wrong."""
    matrix = build_matrix(
        [{"open": time(15, 0), "close": time(21, 0), "service": 15}],
        [[0, 30], [30, 0]],
    )
    results = evaluate_route([1], matrix, 360)
    for r in results:
        assert r.depart_minutes >= r.arrive_minutes
        assert r.start_service_minutes >= r.arrive_minutes


# ---------------------------------------------------------------------------
# Departure recommendation
# ---------------------------------------------------------------------------
def test_recommend_departure_never_leaves_before_the_shift_starts(build_matrix):
    matrix = build_matrix(
        [{"open": time(4, 30), "close": time(20, 30), "service": 15}],
        [[0, 30], [30, 0]],
        depot_loading_minutes=20,
    )
    # The stop opens at 04:30 but the shift cannot start before 06:00.
    departure = recommend_departure(matrix, [1], 360, LONG_SHIFT, BIG_CAPACITY)
    assert departure >= 360


def test_recommend_departure_delays_for_a_late_opening_first_stop(build_matrix):
    matrix = build_matrix(
        [{"open": time(10, 0), "close": time(17, 0), "service": 15}],
        [[0, 60], [60, 0]],
        depot_loading_minutes=20,
    )
    early = recommend_departure(matrix, [1], 360, LONG_SHIFT, BIG_CAPACITY)
    # Leaving at the 06:00 earliest would mean idling outside a closed customer.
    assert early > 360 + 20


def test_recommend_departure_returns_shift_start_for_an_empty_route(build_matrix):
    matrix = build_matrix([], [[0]])
    assert recommend_departure(matrix, [], 360, LONG_SHIFT, BIG_CAPACITY) == 360


# ---------------------------------------------------------------------------
# Assistant determination
# ---------------------------------------------------------------------------
def test_productivity_factor_is_one_for_a_solo_route():
    assert _productivity_factor(0) == 1.0


def test_productivity_factor_decreases_monotonically_with_more_help():
    factors = [_productivity_factor(k) for k in range(0, 5)]
    assert all(b < a for a, b in zip(factors, factors[1:])), factors


def test_productivity_factor_shows_diminishing_returns():
    """Each extra assistant saves less than the one before it."""
    gains = [
        _productivity_factor(k) - _productivity_factor(k + 1)
        for k in range(0, 3)
    ]
    assert all(b < a for a, b in zip(gains, gains[1:])), gains


def test_no_assistants_needed_when_the_route_already_fits(build_matrix):
    matrix = build_matrix([{"service": 15}], [[0, 20], [20, 0]])
    count, feasible = assistants_needed(matrix, [1], 360, 480, BIG_CAPACITY)
    assert (count, feasible) == (0, True)


def test_assistants_are_added_only_until_the_route_becomes_feasible(build_matrix):
    """Service time is the binding constraint, so help should resolve it."""
    matrix = build_matrix([{"service": 300}], [[0, 30], [30, 0]])
    # Solo: 30 + 300 + 30 = 360 > 300-minute shift. One assistant: 300*0.65=195 -> 255. Fits.
    count, feasible = assistants_needed(matrix, [1], 360, 300, BIG_CAPACITY)
    assert feasible is True
    assert count == 1


def test_assistants_cannot_fix_a_capacity_overflow(build_matrix):
    """Extra people shorten service time; they do not make the truck bigger."""
    matrix = build_matrix([{"service": 10, "volume": 500}], [[0, 10], [10, 0]])
    count, feasible = assistants_needed(matrix, [1], 360, LONG_SHIFT, 200)
    assert feasible is False
    assert count == 3


def test_assistants_needed_does_not_mutate_the_caller_matrix(build_matrix):
    """The search scales service times on a copy, not the shared matrix."""
    matrix = build_matrix([{"service": 300}], [[0, 30], [30, 0]])
    before = [n.service_minutes for n in matrix.nodes]
    assistants_needed(matrix, [1], 360, 300, BIG_CAPACITY)
    assert [n.service_minutes for n in matrix.nodes] == before
