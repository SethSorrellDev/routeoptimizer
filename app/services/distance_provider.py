"""DistanceProvider abstraction over OpenRouteService.

The optimizer and geocoding views call this module only — never ORS directly.
Swapping to Google Maps later means rewriting only this file.
"""
import requests
from flask import current_app


ORS_BASE = "https://api.openrouteservice.org"


def _headers():
    return {
        "Authorization": current_app.config["ORS_API_KEY"],
        "Content-Type": "application/json",
    }


def geocode_address(address: str) -> tuple[float, float] | None:
    """Return (latitude, longitude) for a street address, or None on failure.

    Uses the ORS Pelias geocoder (free, no billing setup required).
    """
    url = f"{ORS_BASE}/geocode/search"
    params = {
        "api_key": current_app.config["ORS_API_KEY"],
        "text": address,
        "size": 1,
        "boundary.country": "US",
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        features = r.json().get("features", [])
        if not features:
            return None
        coords = features[0]["geometry"]["coordinates"]
        # ORS returns [longitude, latitude] — swap to (lat, lon)
        return coords[1], coords[0]
    except Exception as e:
        current_app.logger.error(f"Geocoding failed for '{address}': {e}")
        return None


def get_distance_matrix(locations: list[tuple[float, float]]) -> dict | None:
    """Fetch a travel-time + distance matrix for a list of (lat, lon) points.

    locations: list of (latitude, longitude) tuples.
    The matrix endpoint expects [[lon, lat], ...] — we swap internally.
    Returns {"durations": [[...]], "distances": [[...]]} or None on failure.

    Matrix is n x n where index 0 is the first location passed in.
    """
    url = f"{ORS_BASE}/v2/matrix/driving-car"
    # ORS matrix expects [longitude, latitude]
    coords = [[lon, lat] for lat, lon in locations]
    body = {
        "locations": coords,
        "metrics": ["duration", "distance"],
        "units": "m",
    }
    try:
        r = requests.post(url, json=body, headers=_headers(), timeout=30)
        r.raise_for_status()
        data = r.json()
        return {
            "durations": data["durations"],
            "distances": data["distances"],
        }
    except Exception as e:
        current_app.logger.error(f"Distance matrix failed: {e}")
        return None
