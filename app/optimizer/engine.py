"""VRPTW Optimization Engine — RouteOptimizer Phase 3.

Sub-steps built incrementally:
  3a  cost_matrix_from_cache  — assemble duration/distance arrays from DB
  3b  nearest_neighbor        — greedy construction heuristic
  3c  two_opt                 — local search improvement
  3d  constraint checkers     — time window, capacity, shift length
  3e  recommend_departure     — back-calculate smart departure time
  3f  assistants_needed       — fewest assistants that make the shift feasible
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import time, timedelta, datetime
from typing import Optional

from app.models import DistanceMatrixEntry, Route, Stop


# ---------------------------------------------------------------------------
# 3a — Cost matrix assembly
# ---------------------------------------------------------------------------

@dataclass
class Node:
    """One location in the routing problem."""
    index: int           # position in the matrix (0 = depot/plant)
    node_type: str       # 'plant' or 'stop'
    node_id: int         # DB primary key
    name: str
    open_time: Optional[time]    # None = no constraint
    close_time: Optional[time]
    service_minutes: int         # solo service time
    volume_units: int


@dataclass
class CostMatrix:
    """Travel-time and distance matrices for a set of nodes."""
    nodes: list[Node]
    durations: list[list[float]]   # seconds,  n x n
    distances: list[list[float]]   # metres,   n x n

    @property
    def n(self):
        return len(self.nodes)


def cost_matrix_from_cache(route_id: int, day_of_week: str) -> CostMatrix | None:
    """Assemble the cost matrix for a route + day from DistanceMatrixEntry cache.

    Only includes stops whose service_days include the given day letter(s).
    Day letters: M T W R F (R = Thursday, F = Friday).
    Returns None if the plant or any stop is missing coordinates / cache entries.
    """
    route = Route.query.get(route_id)
    if not route:
        return None

    plant = route.plant
    if not plant.latitude or not plant.longitude:
        return None

    # Filter route stops to those that run on this day
    day_upper = day_of_week.upper()
    active_route_stops = [
        rs for rs in route.route_stops
        if rs.service_days and any(d in rs.service_days.upper()
                                   for d in day_upper)
    ]

    if not active_route_stops:
        return None

    # Check all stops have coordinates
    for rs in active_route_stops:
        if not rs.stop.latitude or not rs.stop.longitude:
            return None

    # Build node list: depot at index 0, stops at 1..n
    nodes = [Node(
        index=0,
        node_type="plant",
        node_id=plant.id,
        name=plant.name,
        open_time=plant.shift_start_earliest,
        close_time=None,
        service_minutes=plant.loading_time_minutes,
        volume_units=0,
    )]

    for rs in active_route_stops:
        s = rs.stop
        vol = rs.volume_override if rs.volume_override is not None else s.volume_units
        nodes.append(Node(
            index=len(nodes),
            node_type="stop",
            node_id=s.id,
            name=s.name,
            open_time=s.open_time,
            close_time=s.close_time,
            service_minutes=s.service_time_solo_minutes,
            volume_units=vol,
        ))

    n = len(nodes)
    durations = [[0.0] * n for _ in range(n)]
    distances = [[0.0] * n for _ in range(n)]

    # Pull every pair from cache
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            entry = DistanceMatrixEntry.query.filter_by(
                origin_type=nodes[i].node_type,
                origin_id=nodes[i].node_id,
                dest_type=nodes[j].node_type,
                dest_id=nodes[j].node_id,
            ).first()
            if not entry:
                return None  # missing cache entry — run build_matrix_for_route first
            durations[i][j] = entry.duration_seconds
            distances[i][j] = entry.distance_meters

    return CostMatrix(nodes=nodes, durations=durations, distances=distances)


# ---------------------------------------------------------------------------
# 3b — Nearest-Neighbor construction heuristic
# ---------------------------------------------------------------------------

def _time_to_minutes(t: time) -> float:
    return t.hour * 60 + t.minute + t.second / 60


def nearest_neighbor(matrix: CostMatrix,
                     departure_minutes: float) -> list[int]:
    """Greedy construction: start at depot, repeatedly go to the nearest
    feasible unvisited stop (minimising travel + wait time).

    departure_minutes: minutes since midnight the truck leaves the depot.
    Returns an ordered list of node indices (not including depot at start/end).
    """
    n = matrix.n
    unvisited = set(range(1, n))  # all stops
    route = []
    current = 0  # start at depot
    current_time = departure_minutes + matrix.nodes[0].service_minutes

    while unvisited:
        best = None
        best_cost = float("inf")

        for j in unvisited:
            travel = matrix.durations[current][j] / 60  # convert to minutes
            arrive = current_time + travel
            node = matrix.nodes[j]

            # Respect time window — can wait if early, but can't arrive late
            if node.close_time:
                close_min = _time_to_minutes(node.close_time)
                if arrive > close_min:
                    continue  # infeasible — skip

            # Cost = travel time + any waiting time
            if node.open_time:
                open_min = _time_to_minutes(node.open_time)
                wait = max(0.0, open_min - arrive)
            else:
                wait = 0.0

            cost = travel + wait
            if cost < best_cost:
                best_cost = cost
                best = j

        if best is None:
            # No feasible stop reachable — add remaining in arbitrary order
            route.extend(sorted(unvisited))
            break

        route.append(best)
        unvisited.remove(best)

        # Advance time
        travel = matrix.durations[current][best] / 60
        arrive = current_time + travel
        node = matrix.nodes[best]
        if node.open_time:
            open_min = _time_to_minutes(node.open_time)
            start_service = max(arrive, open_min)
        else:
            start_service = arrive
        current_time = start_service + node.service_minutes
        current = best

    return route


# ---------------------------------------------------------------------------
# 3c — 2-opt improvement
# ---------------------------------------------------------------------------

def _route_duration(order: list[int], matrix: CostMatrix,
                    departure_minutes: float) -> float:
    """Total elapsed minutes from departure to return to depot."""
    current_time = departure_minutes + matrix.nodes[0].service_minutes
    current = 0
    for idx in order:
        travel = matrix.durations[current][idx] / 60
        arrive = current_time + travel
        node = matrix.nodes[idx]
        if node.open_time:
            open_min = _time_to_minutes(node.open_time)
            start_service = max(arrive, open_min)
        else:
            start_service = arrive
        current_time = start_service + node.service_minutes
        current = idx
    # Return to depot
    current_time += matrix.durations[current][0] / 60
    return current_time - departure_minutes


def _is_feasible(order: list[int], matrix: CostMatrix,
                 departure_minutes: float,
                 max_shift_minutes: int,
                 truck_capacity: int) -> bool:
    """Check time windows, capacity, and shift length for an ordering."""
    current_time = departure_minutes + matrix.nodes[0].service_minutes
    current = 0
    cumulative_volume = 0

    for idx in order:
        travel = matrix.durations[current][idx] / 60
        arrive = current_time + travel
        node = matrix.nodes[idx]

        # Time window check
        if node.close_time:
            close_min = _time_to_minutes(node.close_time)
            if arrive > close_min:
                return False

        if node.open_time:
            open_min = _time_to_minutes(node.open_time)
            start_service = max(arrive, open_min)
        else:
            start_service = arrive

        current_time = start_service + node.service_minutes
        current = idx

        # Capacity check
        cumulative_volume += node.volume_units
        if cumulative_volume > truck_capacity:
            return False

    # Shift length check
    return_time = current_time + matrix.durations[current][0] / 60
    if return_time - departure_minutes > max_shift_minutes:
        return False

    return True


def two_opt(order: list[int], matrix: CostMatrix,
            departure_minutes: float,
            max_shift_minutes: int,
            truck_capacity: int) -> list[int]:
    """Improve the route by reversing every contiguous segment.

    Only accepts a reversal if it shortens total time AND stays feasible.
    Repeats until no improvement is found.
    """
    best = order[:]
    best_duration = _route_duration(best, matrix, departure_minutes)
    improved = True

    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                candidate = best[:i] + best[i:j+1][::-1] + best[j+1:]
                if not _is_feasible(candidate, matrix, departure_minutes,
                                    max_shift_minutes, truck_capacity):
                    continue
                duration = _route_duration(candidate, matrix, departure_minutes)
                if duration < best_duration - 0.01:  # 0.01 min tolerance
                    best = candidate
                    best_duration = duration
                    improved = True
                    break
            if improved:
                break

    return best


# ---------------------------------------------------------------------------
# 3d — Constraint checkers (used above + exposed for results display)
# ---------------------------------------------------------------------------

@dataclass
class StopResult:
    """Computed arrival/departure times and feasibility for one stop."""
    node: Node
    sequence: int
    arrive_minutes: float
    start_service_minutes: float
    depart_minutes: float
    cumulative_volume: int
    time_window_ok: bool
    wait_minutes: float


def evaluate_route(order: list[int], matrix: CostMatrix,
                   departure_minutes: float) -> list[StopResult]:
    """Walk the route and compute per-stop timing + feasibility."""
    results = []
    current_time = departure_minutes + matrix.nodes[0].service_minutes
    current = 0
    cumulative_volume = 0

    for seq, idx in enumerate(order, start=1):
        travel = matrix.durations[current][idx] / 60
        arrive = current_time + travel
        node = matrix.nodes[idx]

        if node.open_time:
            open_min = _time_to_minutes(node.open_time)
            start_service = max(arrive, open_min)
            wait = max(0.0, open_min - arrive)
        else:
            start_service = arrive
            wait = 0.0

        time_window_ok = True
        if node.close_time:
            close_min = _time_to_minutes(node.close_time)
            if arrive > close_min:
                time_window_ok = False

        depart = start_service + node.service_minutes
        cumulative_volume += node.volume_units

        results.append(StopResult(
            node=node,
            sequence=seq,
            arrive_minutes=arrive,
            start_service_minutes=start_service,
            depart_minutes=depart,
            cumulative_volume=cumulative_volume,
            time_window_ok=time_window_ok,
            wait_minutes=wait,
        ))

        current_time = depart
        current = idx

    return results


# ---------------------------------------------------------------------------
# 3e — Recommended departure time
# ---------------------------------------------------------------------------

def recommend_departure(matrix: CostMatrix,
                        order: list[int],
                        shift_start_earliest_minutes: float,
                        max_shift_minutes: int,
                        truck_capacity: int) -> float:
    """Find the latest departure time that keeps the full route feasible.

    Strategy: leave no earlier than shift_start_earliest, and no earlier
    than needed to reach the first stop before it closes. Then push departure
    as late as possible (so the SSR isn't idling outside a closed stop) while
    the route stays fully feasible.
    """
    if not order:
        return shift_start_earliest_minutes

    # Earliest possible: shift start + loading time
    loading = matrix.nodes[0].service_minutes
    earliest = shift_start_earliest_minutes

    # Don't leave so early that the first stop isn't open yet — push to arrive
    # exactly at open_time of the first stop if possible
    first_node = matrix.nodes[order[0]]
    travel_to_first = matrix.durations[0][order[0]] / 60

    if first_node.open_time:
        open_min = _time_to_minutes(first_node.open_time)
        # Ideal departure: arrive exactly at open
        ideal = open_min - travel_to_first - loading
        departure = max(earliest, ideal)
    else:
        departure = earliest

    # Verify feasibility; if not, fall back to earliest
    if not _is_feasible(order, matrix, departure + loading,
                        max_shift_minutes, truck_capacity):
        departure = earliest

    return departure + loading  # return actual departure (after loading)


# ---------------------------------------------------------------------------
# 3f — Assistant determination
# ---------------------------------------------------------------------------

def _productivity_factor(num_assistants: int) -> float:
    """Service-time multiplier given N assistants.

    k=0 -> 1.0 (solo)
    k=1 -> 0.65 (one assistant saves ~35%)
    k=2 -> 0.50
    k=3 -> 0.42
    Diminishing returns per the plan (coordination overhead).
    """
    factors = {0: 1.0, 1: 0.65, 2: 0.50, 3: 0.42}
    return factors.get(num_assistants, 0.38)


def assistants_needed(matrix: CostMatrix,
                      order: list[int],
                      departure_minutes: float,
                      max_shift_minutes: int,
                      truck_capacity: int,
                      max_assistants: int = 3) -> tuple[int, bool]:
    """Find the fewest assistants that make the route feasible.

    Returns (num_assistants, feasible).
    Adjusts service times by the productivity factor for each k.
    """
    from copy import deepcopy

    for k in range(0, max_assistants + 1):
        factor = _productivity_factor(k)
        # Build a modified matrix with scaled service times
        scaled = deepcopy(matrix)
        for node in scaled.nodes:
            if node.node_type == "stop":
                node.service_minutes = int(node.service_minutes * factor)

        if _is_feasible(order, scaled, departure_minutes,
                        max_shift_minutes, truck_capacity):
            return k, True

    return max_assistants, False


# ---------------------------------------------------------------------------
# Main entry point — run the full optimizer for a route + day
# ---------------------------------------------------------------------------

@dataclass
class OptimizationPlan:
    """Complete output of one optimization run."""
    route_id: int
    day_of_week: str
    departure_minutes: float
    order: list[int]
    stop_results: list[StopResult]
    assistants: int
    feasible: bool
    total_distance_m: float
    total_drive_seconds: float
    total_service_seconds: float
    capacity_utilization_pct: float
    estimated_return_minutes: float
    warnings: list[str] = field(default_factory=list)


def optimize(route_id: int, day_of_week: str) -> OptimizationPlan | None:
    """Run the full VRPTW optimization pipeline for a route + day.

    Steps: 3a -> 3b -> 3c -> 3d -> 3e -> 3f
    Returns an OptimizationPlan or None if the matrix is missing.
    """
    matrix = cost_matrix_from_cache(route_id, day_of_week)
    if not matrix:
        return None

    route = Route.query.get(route_id)
    max_shift = route.plant.max_shift_minutes
    capacity = route.truck_capacity_volume
    shift_start = _time_to_minutes(route.plant.shift_start_earliest)
    loading = route.plant.loading_time_minutes

    # 3b — initial route via nearest neighbor
    initial_departure = shift_start + loading
    order = nearest_neighbor(matrix, initial_departure)

    # 3c — improve with 2-opt
    order = two_opt(order, matrix, initial_departure, max_shift, capacity)

    # 3e — recommended departure
    departure = recommend_departure(matrix, order, shift_start, max_shift, capacity)

    # 3f — assistant determination
    num_assistants, feasible = assistants_needed(
        matrix, order, departure, max_shift, capacity
    )

    # 3d — evaluate final route for display
    stop_results = evaluate_route(order, matrix, departure)

    # Totals
    warnings = []
    total_distance = 0.0
    total_drive = 0.0
    total_service = 0.0
    cumulative_vol = 0

    current = 0
    for sr in stop_results:
        idx = sr.node.index
        total_distance += matrix.distances[current][idx]
        total_drive += matrix.durations[current][idx]
        total_service += sr.node.service_minutes * 60
        cumulative_vol = sr.cumulative_volume
        current = idx
        if not sr.time_window_ok:
            warnings.append(
                f"{sr.node.name}: arrives after close time — infeasible window."
            )

    # Add return leg
    total_distance += matrix.distances[current][0]
    total_drive += matrix.durations[current][0]

    # Base the return estimate on the last stop's actual (wait-inclusive)
    # departure time, not a re-summed drive+service total — that summation
    # silently dropped wait time, understating the return whenever a stop's
    # window forced the truck to wait before service could start.
    if stop_results:
        last_depart = stop_results[-1].depart_minutes
        return_travel_minutes = matrix.durations[current][0] / 60
        estimated_return = last_depart + return_travel_minutes
    else:
        estimated_return = departure

    cap_pct = (cumulative_vol / capacity * 100) if capacity > 0 else 0.0

    if not feasible:
        warnings.append(
            "Route cannot be completed in one shift even with maximum assistants."
        )

    return OptimizationPlan(
        route_id=route_id,
        day_of_week=day_of_week,
        departure_minutes=departure,
        order=order,
        stop_results=stop_results,
        assistants=num_assistants,
        feasible=feasible,
        total_distance_m=total_distance,
        total_drive_seconds=total_drive,
        total_service_seconds=total_service,
        capacity_utilization_pct=cap_pct,
        estimated_return_minutes=estimated_return,
        warnings=warnings,
    )
