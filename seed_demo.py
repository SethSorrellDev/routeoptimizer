"""Seed a realistic demo route so a fresh install has something to optimize.

This is the Kokomo run used in the screenshots: five normal-route stops out of
the Frankfort plant, with the real service windows and volumes.

Stops are seeded WITHOUT coordinates on purpose. Geocoding requires an
OpenRouteService key, so this script seeds the records and then geocodes only
if ORS_API_KEY is configured; otherwise it tells you what to do next. Nothing
here invents a latitude.

    python seed_demo.py

A demo login is created only when DEMO_USERNAME and DEMO_PASSWORD are set in
the environment, so no credentials ever live in this repository.
"""
import os
from datetime import time

from app.extensions import db
from app.models import Plant, Role, Route, RouteStop, Stop, User

ROUTE_NAME = "Route 64"
TRUCK_CAPACITY = 200
SERVICE_DAYS = "WF"

DEMO_STOPS = [
    {
        "name": "Starbucks Coffee Company",
        "address": "Southway Plaza, 512 E Alto Rd, Kokomo, IN 46902",
        "service_type": "mixed",
        "open": time(4, 30), "close": time(20, 30),
        "service": 15, "volume": 30,
    },
    {
        "name": "Meijer",
        "address": "2301 E Markland Ave, Kokomo, IN 46901",
        "service_type": "mats",
        "open": time(6, 0), "close": time(12, 0),
        "service": 15, "volume": 25,
    },
    {
        "name": "Specialty Tool and Die",
        "address": "1614 Rank Pkwy Ct, Kokomo, IN 46901",
        "service_type": "uniforms",
        "open": time(7, 0), "close": time(17, 0),
        "service": 10, "volume": 12,
    },
    {
        "name": "Taylor High School",
        "address": "3794 E 300 S, Kokomo, IN 46902",
        "service_type": "mats",
        "open": time(6, 30), "close": time(8, 0),
        "service": 10, "volume": 50,
    },
    {
        "name": "Chipotle Mexican Grill",
        "address": "3865 S Lafountain St, Kokomo, IN 46902",
        "service_type": "mixed",
        "open": time(9, 0), "close": time(22, 0),
        "service": 15, "volume": 40,
    },
]


def seed_demo_route():
    """Create the demo route and its stops. Returns (route, created_stop_names)."""
    plant = Plant.query.first()
    if plant is None:
        raise RuntimeError("No plant found — run seed_plant.py first.")

    route = Route.query.filter_by(name=ROUTE_NAME).first()
    if route is None:
        route = Route(
            name=ROUTE_NAME,
            plant_id=plant.id,
            truck_capacity_volume=TRUCK_CAPACITY,
        )
        db.session.add(route)
        db.session.flush()

    created = []
    for spec in DEMO_STOPS:
        stop = Stop.query.filter_by(plant_id=plant.id, name=spec["name"]).first()
        if stop is None:
            stop = Stop(
                plant_id=plant.id,
                name=spec["name"],
                address=spec["address"],
                service_type=spec["service_type"],
                service_time_solo_minutes=spec["service"],
                open_time=spec["open"],
                close_time=spec["close"],
                volume_units=spec["volume"],
            )
            db.session.add(stop)
            db.session.flush()
            created.append(stop.name)

        link = RouteStop.query.filter_by(route_id=route.id, stop_id=stop.id).first()
        if link is None:
            db.session.add(RouteStop(
                route_id=route.id, stop_id=stop.id, service_days=SERVICE_DAYS,
            ))

    db.session.commit()
    return route, created


def seed_demo_user(username, password, email=None, role_name="Manager"):
    """Create a demo login from caller-supplied credentials. Never hardcoded."""
    existing = User.query.filter_by(username=username).first()
    if existing is not None:
        return existing, False

    role = Role.query.filter_by(name=role_name).first()
    if role is None:
        raise RuntimeError(f"Role {role_name!r} not found — run seed_roles.py first.")

    user = User(
        username=username,
        email=email or f"{username}@example.invalid",
        name="Demo Manager",
        role_id=role.id,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user, True


if __name__ == "__main__":
    from app import create_app

    app = create_app()
    with app.app_context():
        route, created = seed_demo_route()
        print(f"Route: {route.name} ({len(route.route_stops)} stops, "
              f"{route.truck_capacity_volume}-unit truck, service days {SERVICE_DAYS})")
        print("Stops created:", ", ".join(created) if created else "none (already present)")

        demo_user = os.environ.get("DEMO_USERNAME")
        demo_pass = os.environ.get("DEMO_PASSWORD")
        if demo_user and demo_pass:
            user, was_created = seed_demo_user(demo_user, demo_pass)
            print(f"Demo login {'created' if was_created else 'already exists'}: {user.username}")
        else:
            print("Demo login skipped (set DEMO_USERNAME and DEMO_PASSWORD to create one).")

        if app.config.get("ORS_API_KEY"):
            from app.services.geocoding import geocode_all_stops
            result = geocode_all_stops(Plant.query.first().id)
            print("Geocoded:", ", ".join(result["updated"]) or "nothing new")
            if result["failed"]:
                print("Failed to geocode:", ", ".join(result["failed"]))
                print("Set those coordinates by hand on each stop's edit page.")
        else:
            print("\nNo ORS_API_KEY set, so stops have no coordinates yet.")
            print("Add a key to .env, then re-run this script (or use the")
            print("'Re-geocode from address' button on each stop) before optimizing.")
