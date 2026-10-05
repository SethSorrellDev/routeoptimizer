"""Seed a fully fictional sample data set: two routes, fifteen stops, and the
travel-time cache the optimizer reads, so a fresh install (or a screenshot
session) never needs real customer data.

Everything here is invented. Business names, street addresses and phone
numbers are made up (phones use the reserved 555-01xx range). Coordinates are
scattered around the plant so the map looks like a real service area, but they
do not correspond to any real customer.

Travel times are SYNTHETIC: straight-line distance x 1.35 for road winding, at
an average of 50 km/h, with a small deterministic asymmetry between directions.
They are written straight into the distance-matrix cache, which is exactly
where the optimizer reads them, so no routing API key is needed.

    python seed_sample.py            # add the sample data (safe to re-run)
    python seed_sample.py --remove   # delete only what this script created

Route A is comfortably feasible. Route B is deliberately over-constrained
(two far-apart stops that both close within the same half hour), so it
demonstrates the window warnings.
"""
import math
import sys
from datetime import date, time, timedelta

from app.extensions import db
from app.models import (
    DistanceMatrixEntry, OptimizationResult, Plant, Route, RouteStop, Stop,
    StopClosure, StopContact,
)

ROUTE_A = "Sample Route A (North Loop)"
ROUTE_B = "Sample Route B (South, tight windows)"
TRUCK_CAPACITY = 200
ROAD_FACTOR = 1.35
SPEED_KMH = 50.0
MIN_LEG_SECONDS = 120

# (name, address, dx_km_east, dy_km_north, service_type, open, close,
#  service_minutes, volume, instructions, contact)
_A = [
    ("Ridgeview Dental Group", "210 Sample Ave, Exampleton, IN 46000", 3.0, 6.5,
     "uniforms", time(7, 0), time(17, 0), 10, 14,
     "Deliver to front desk.", ("Dana Reyes", "555-0101")),
    ("Bluebird Diner", "48 Mill St, Exampleton, IN 46000", 6.0, 9.0,
     "mixed", time(5, 0), time(14, 0), 15, 28,
     "Back door by the dumpster enclosure.", ("Marcus Lee", "555-0102")),
    ("Pinecrest Elementary", "900 School Rd, Pinecrest, IN 46001", -2.5, 12.0,
     "mats", time(6, 30), time(9, 0), 10, 36,
     "Check in at the office first.", ("Front office", "555-0103")),
    ("Harlan Auto Care", "17 Garage Ln, Pinecrest, IN 46001", 4.5, 14.5,
     "uniforms", time(7, 30), time(17, 30), 12, 22,
     "Bay 2 side door.", ("Tom Harlan", "555-0104")),
    ("Maple Court Apartments", "5 Maple Ct, Exampleton, IN 46000", 8.5, 5.0,
     "mats", time(8, 0), time(16, 0), 8, 18,
     "Leave mats in the leasing office.", ("Priya Nair", "555-0105")),
    ("Copperline Machine Works", "1200 Industrial Pkwy, Exampleton, IN 46000", 11.0, 8.5,
     "uniforms", time(6, 0), time(15, 0), 20, 45,
     "Dock door 3. Check in with the shipping lead.", ("Shipping desk", "555-0106")),
    ("Lakeshore Family Pharmacy", "77 Lake Rd, Lakeshore, IN 46002", 13.0, 12.5,
     "mixed", time(8, 30), time(18, 0), 10, 20,
     "Ring bell at the rear entrance.", ("Aisha Khan", "555-0107")),
    ("Northgate Credit Union", "300 Commerce Dr, Lakeshore, IN 46002", 9.5, 15.5,
     "mats", time(9, 0), time(17, 0), 8, 15,
     "Lobby mats only.", ("Branch manager", "555-0108")),
]

_B = [
    ("Eastwind Bakery", "12 Baker St, Southford, IN 46010", 5.0, -8.0,
     "mixed", time(4, 30), time(11, 0), 15, 30,
     "Deliver before the lunch rush.", ("Lena Ortiz", "555-0111")),
    ("Granite State Fitness", "640 Fitness Way, Southford, IN 46010", 9.0, -11.5,
     "uniforms", time(6, 0), time(21, 0), 12, 26,
     "Staff entrance on the east side.", ("Front desk", "555-0112")),
    ("Redhill Elementary", "400 Hill Rd, Redhill, IN 46011", -4.0, -13.0,
     "mats", time(6, 30), time(8, 30), 10, 40,
     "Check in at the office first.", ("Front office", "555-0113")),
    ("Summit Tire & Lube", "88 Tire Row, Southford, IN 46010", 12.0, -6.5,
     "uniforms", time(7, 0), time(17, 0), 10, 24,
     "Service desk, ask for the shop foreman.", ("Rick Dalton", "555-0114")),
    # The deliberate conflict: both close within 30 minutes of each other and
    # sit on opposite sides of the plant.
    ("Early Bird Cafe", "2 Dawn St, Redhill, IN 46011", -9.0, -10.0,
     "mixed", time(6, 30), time(7, 15), 12, 20,
     "Opens early, closes the dock at 7:15.", ("Nora Webb", "555-0115")),
    ("Quarry Road Concrete", "5100 Quarry Rd, Southford, IN 46010", 16.0, -9.5,
     "uniforms", time(6, 30), time(7, 15), 20, 38,
     "Gate closes at 7:15. Ask for the dispatcher.", ("Dispatcher", "555-0116")),
]

ROUTES = [
    {"name": ROUTE_A, "stops": _A, "days": "MWF", "extra_stops": []},
    {"name": ROUTE_B, "stops": _B, "days": "TR", "extra_stops": [("Maple Court Apartments", "TR")]},
]

SAMPLE_STOP_NAMES = [s[0] for s in _A] + [s[0] for s in _B]
SAMPLE_ROUTE_NAMES = [ROUTE_A, ROUTE_B]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def _offset(plant, dx_km, dy_km):
    lat = plant.latitude + dy_km / 111.32
    lon = plant.longitude + dx_km / (111.32 * math.cos(math.radians(plant.latitude)))
    return round(lat, 6), round(lon, 6)


def _haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def synthetic_leg(a, b, a_key, b_key):
    """(distance_m, duration_s) for a->b. Slightly asymmetric by direction."""
    straight = _haversine_m(a[0], a[1], b[0], b[1])
    road = straight * ROAD_FACTOR * (1.03 if a_key < b_key else 1.0)
    seconds = max(MIN_LEG_SECONDS, road / (SPEED_KMH * 1000 / 3600))
    return round(road, 1), round(seconds, 1)


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
def _ensure_stop(plant, spec):
    name, address, dx, dy, stype, opn, cls, svc, vol, instr, contact = spec
    stop = Stop.query.filter_by(plant_id=plant.id, name=name).first()
    if stop is not None:
        return stop, False
    lat, lon = _offset(plant, dx, dy)
    stop = Stop(
        plant_id=plant.id, name=name, address=address,
        latitude=lat, longitude=lon, service_type=stype,
        service_time_solo_minutes=svc, open_time=opn, close_time=cls,
        volume_units=vol, special_instructions=instr,
    )
    db.session.add(stop)
    db.session.flush()
    db.session.add(StopContact(stop_id=stop.id, name=contact[0], phone=contact[1]))
    return stop, True


def _ensure_link(route, stop, days):
    link = RouteStop.query.filter_by(route_id=route.id, stop_id=stop.id).first()
    if link is None:
        db.session.add(RouteStop(route_id=route.id, stop_id=stop.id, service_days=days))
        return True
    return False


def _fill_matrix(plant, stops):
    """Write every ordered pair among the plant and the given stops."""
    nodes = [("plant", plant.id, (plant.latitude, plant.longitude))]
    nodes += [("stop", s.id, (s.latitude, s.longitude)) for s in stops]
    added = 0
    for i, (t1, id1, p1) in enumerate(nodes):
        for j, (t2, id2, p2) in enumerate(nodes):
            if i == j:
                continue
            exists = DistanceMatrixEntry.query.filter_by(
                origin_type=t1, origin_id=id1, dest_type=t2, dest_id=id2).first()
            if exists:
                continue
            dist, secs = synthetic_leg(p1, p2, i, j)
            db.session.add(DistanceMatrixEntry(
                origin_type=t1, origin_id=id1, dest_type=t2, dest_id=id2,
                distance_meters=dist, duration_seconds=secs))
            added += 1
    return added


def seed_sample():
    """Add the sample routes, stops, contacts and travel-time cache.

    Returns a dict of counts for what was newly created.
    """
    plant = Plant.query.first()
    if plant is None or plant.latitude is None or plant.longitude is None:
        raise RuntimeError("No plant with coordinates found — run seed_plant.py first.")

    counts = {"routes": 0, "stops": 0, "links": 0, "matrix_entries": 0, "closures": 0}
    all_stops = []

    for rdef in ROUTES:
        route = Route.query.filter_by(name=rdef["name"]).first()
        if route is None:
            route = Route(name=rdef["name"], plant_id=plant.id,
                          truck_capacity_volume=TRUCK_CAPACITY)
            db.session.add(route)
            db.session.flush()
            counts["routes"] += 1
        for spec in rdef["stops"]:
            stop, created = _ensure_stop(plant, spec)
            counts["stops"] += int(created)
            counts["links"] += int(_ensure_link(route, stop, rdef["days"]))
            all_stops.append(stop)
        for name, days in rdef["extra_stops"]:
            stop = Stop.query.filter_by(plant_id=plant.id, name=name).first()
            counts["links"] += int(_ensure_link(route, stop, days))
            all_stops.append(stop)

    unique = {s.id: s for s in all_stops}
    # One cache covering every pair keeps every route's lookup complete.
    counts["matrix_entries"] = _fill_matrix(plant, list(unique.values()))

    # One stop closed next week, to show the closure handling.
    closed = Stop.query.filter_by(plant_id=plant.id, name="Pinecrest Elementary").first()
    when = date.today() + timedelta(days=7)
    if closed and not StopClosure.query.filter_by(stop_id=closed.id, date=when).first() \
            and StopClosure.query.filter_by(stop_id=closed.id).count() == 0:
        db.session.add(StopClosure(stop_id=closed.id, date=when))
        counts["closures"] += 1

    db.session.commit()
    return counts


def remove_sample():
    """Delete only what seed_sample created. Returns a dict of counts."""
    plant = Plant.query.first()
    counts = {"routes": 0, "stops": 0, "matrix_entries": 0}
    if plant is None:
        return counts

    stops = Stop.query.filter(
        Stop.plant_id == plant.id, Stop.name.in_(SAMPLE_STOP_NAMES)).all()
    stop_ids = [s.id for s in stops]
    routes = Route.query.filter(Route.name.in_(SAMPLE_ROUTE_NAMES)).all()

    for route in routes:
        for res in OptimizationResult.query.filter_by(route_id=route.id).all():
            db.session.delete(res)  # cascades to its result stops
        RouteStop.query.filter_by(route_id=route.id).delete()
        db.session.delete(route)
        counts["routes"] += 1
    db.session.flush()

    if stop_ids:
        from app.models import OptimizationResultStop
        OptimizationResultStop.query.filter(
            OptimizationResultStop.stop_id.in_(stop_ids)).delete(synchronize_session=False)
        RouteStop.query.filter(RouteStop.stop_id.in_(stop_ids)).delete(synchronize_session=False)
        StopClosure.query.filter(StopClosure.stop_id.in_(stop_ids)).delete(synchronize_session=False)
        StopContact.query.filter(StopContact.stop_id.in_(stop_ids)).delete(synchronize_session=False)
        counts["matrix_entries"] = DistanceMatrixEntry.query.filter(
            ((DistanceMatrixEntry.origin_type == "stop") & DistanceMatrixEntry.origin_id.in_(stop_ids))
            | ((DistanceMatrixEntry.dest_type == "stop") & DistanceMatrixEntry.dest_id.in_(stop_ids))
        ).delete(synchronize_session=False)
        for s in stops:
            db.session.delete(s)
            counts["stops"] += 1

    db.session.commit()
    return counts


if __name__ == "__main__":
    from app import create_app

    app = create_app()
    with app.app_context():
        if "--remove" in sys.argv:
            print("Removed:", remove_sample())
        else:
            print("Added:", seed_sample())
            print("Open a route, pick a service day (A: M/W/F, B: T/R) and click Optimize.")
