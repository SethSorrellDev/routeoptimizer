"""Geocoding service: resolve addresses to lat/lon and persist to the DB."""
from app.extensions import db
from app.models import Plant, Stop
from app.services.distance_provider import geocode_address


def _ensure_state(address: str) -> str:
    """Append Indiana state hint if address doesn't already mention it.

    ORS picks wrong locations when the state is ambiguous (e.g. 'Nucor'
    exists in many states). Appending ', IN, USA' biases results toward
    Indiana without breaking addresses that already include the state.
    """
    address = address.strip()
    upper = address.upper()
    if "IN" in upper or "INDIANA" in upper:
        return address
    return address + ", IN, USA"


def geocode_plant(plant: Plant) -> bool:
    """Geocode the plant if lat/lon is missing. Returns True if updated."""
    if plant.latitude and plant.longitude:
        return False
    if not plant.address:
        return False
    result = geocode_address(_ensure_state(plant.address))
    if not result:
        return False
    plant.latitude, plant.longitude = result
    db.session.commit()
    return True


def geocode_stop(stop: Stop) -> bool:
    """Geocode a stop (or re-geocode it). Returns True if updated."""
    if not stop.address:
        return False
    result = geocode_address(_ensure_state(stop.address))
    if not result:
        return False
    stop.latitude, stop.longitude = result
    db.session.commit()
    return True


def geocode_all_stops(plant_id: int) -> dict:
    """Geocode every stop under a plant that is missing coordinates.

    Returns {"updated": [...], "skipped": [...], "failed": [...]}
    """
    stops = Stop.query.filter_by(plant_id=plant_id).all()
    updated, skipped, failed = [], [], []

    for stop in stops:
        if stop.latitude and stop.longitude:
            skipped.append(stop.name)
            continue
        if not stop.address:
            skipped.append(stop.name)
            continue
        result = geocode_address(_ensure_state(stop.address))
        if result:
            stop.latitude, stop.longitude = result
            updated.append(stop.name)
        else:
            failed.append(stop.name)

    db.session.commit()
    return {"updated": updated, "skipped": skipped, "failed": failed}
