"""Seed the Cintas Frankfort plant (the depot every route starts and ends at).

Coordinates are set explicitly rather than left to the geocoder for two reasons:

1. A plant row without latitude/longitude makes every optimizer run fail with
   "Distance matrix could not be built" — the matrix builder needs a depot
   position before it can ask the routing provider for anything.
2. The plant's rural county-road address geocodes to a point roughly three
   miles north of the actual building, so the value below is the verified
   building location rather than whatever the geocoder returns.
"""
from datetime import time

from app.extensions import db
from app.models import Plant

PLANT_NAME = "Cintas Uniform Services"
PLANT_ADDRESS = "3470 W County Rd 0 N/S, Frankfort, IN 46041"
PLANT_LATITUDE = 40.287528634526396
PLANT_LONGITUDE = -86.57083716973595
LOADING_TIME_MINUTES = 20
SHIFT_START_EARLIEST = time(6, 0)
MAX_SHIFT_MINUTES = 600


def seed_plant():
    """Create the plant, or backfill coordinates on an existing one.

    Returns (plant, action) where action is 'created', 'backfilled coordinates'
    or 'unchanged', so the caller can report what actually happened.
    """
    plant = Plant.query.first()

    if plant is None:
        plant = Plant(
            name=PLANT_NAME,
            address=PLANT_ADDRESS,
            latitude=PLANT_LATITUDE,
            longitude=PLANT_LONGITUDE,
            loading_time_minutes=LOADING_TIME_MINUTES,
            shift_start_earliest=SHIFT_START_EARLIEST,
            max_shift_minutes=MAX_SHIFT_MINUTES,
        )
        db.session.add(plant)
        db.session.commit()
        return plant, "created"

    if plant.latitude is None or plant.longitude is None:
        plant.latitude = PLANT_LATITUDE
        plant.longitude = PLANT_LONGITUDE
        db.session.commit()
        return plant, "backfilled coordinates"

    return plant, "unchanged"


if __name__ == "__main__":
    from app import create_app

    app = create_app()
    with app.app_context():
        plant, action = seed_plant()
        print(f"Plant {action}: {plant.name}")
        print(f"  {plant.address}")
        print(f"  ({plant.latitude}, {plant.longitude})")
