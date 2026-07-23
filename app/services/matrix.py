"""Distance matrix service.

Builds and caches the travel-time/distance matrix for a route.
All results are stored in DistanceMatrixEntry so the ORS API is only
called for pairs that are missing or stale.
"""
from datetime import datetime, timezone

from app.extensions import db
from app.models import Plant, Stop, DistanceMatrixEntry
from app.services.distance_provider import get_distance_matrix


def _get_cached(origin_type, origin_id, dest_type, dest_id):
    return DistanceMatrixEntry.query.filter_by(
        origin_type=origin_type,
        origin_id=origin_id,
        dest_type=dest_type,
        dest_id=dest_id,
    ).first()


def _save_entry(origin_type, origin_id, dest_type, dest_id,
                distance_meters, duration_seconds):
    entry = _get_cached(origin_type, origin_id, dest_type, dest_id)
    if entry:
        entry.distance_meters = distance_meters
        entry.duration_seconds = duration_seconds
        entry.fetched_at = datetime.now(timezone.utc)
    else:
        entry = DistanceMatrixEntry(
            origin_type=origin_type,
            origin_id=origin_id,
            dest_type=dest_type,
            dest_id=dest_id,
            distance_meters=distance_meters,
            duration_seconds=duration_seconds,
        )
        db.session.add(entry)


def build_matrix_for_route(route_id: int) -> dict:
    """Build (or refresh from cache) the full distance matrix for a route.

    Nodes: plant (index 0) + every stop on the route (indices 1..n).
    Only calls ORS for the full batch if ANY pair is missing from the cache.

    Returns:
      {
        "nodes": [{"type": "plant"|"stop", "id": int, "name": str}, ...],
        "durations": [[seconds, ...], ...],   # n+1 x n+1
        "distances": [[meters,  ...], ...],   # n+1 x n+1
      }
    """
    from app.models import Route

    route = Route.query.get(route_id)
    if not route:
        return {}

    plant = route.plant
    stops = [rs.stop for rs in route.route_stops]

    # Build the ordered node list: plant first, then stops
    nodes = [{"type": "plant", "id": plant.id, "name": plant.name,
              "lat": plant.latitude, "lon": plant.longitude}]
    for stop in stops:
        nodes.append({"type": "stop", "id": stop.id, "name": stop.name,
                      "lat": stop.latitude, "lon": stop.longitude})

    n = len(nodes)

    # Check whether all pairs are already cached
    all_cached = True
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            entry = _get_cached(
                nodes[i]["type"], nodes[i]["id"],
                nodes[j]["type"], nodes[j]["id"],
            )
            if not entry:
                all_cached = False
                break
        if not all_cached:
            break

    if not all_cached:
        # Fetch the full matrix from ORS in one API call
        locations = [(node["lat"], node["lon"]) for node in nodes]
        result = get_distance_matrix(locations)
        if not result:
            return {}

        durations = result["durations"]
        distances = result["distances"]

        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                _save_entry(
                    nodes[i]["type"], nodes[i]["id"],
                    nodes[j]["type"], nodes[j]["id"],
                    distances[i][j], durations[i][j],
                )
        db.session.commit()

    # Read back from cache into matrices
    durations_out = [[0.0] * n for _ in range(n)]
    distances_out = [[0.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            entry = _get_cached(
                nodes[i]["type"], nodes[i]["id"],
                nodes[j]["type"], nodes[j]["id"],
            )
            if entry:
                durations_out[i][j] = entry.duration_seconds
                distances_out[i][j] = entry.distance_meters

    return {
        "nodes": nodes,
        "durations": durations_out,
        "distances": distances_out,
    }
