from datetime import time
from app import create_app
from app.extensions import db
from app.models import Plant

app = create_app()
with app.app_context():
    if Plant.query.first():
        print("Plant already exists — skipping.")
    else:
        plant = Plant(
            name="Cintas — Frankfort",
            address="3470 W County Rd 0 N/S, Frankfort, IN 46041",
            loading_time_minutes=20,
            shift_start_earliest=time(6, 0),
            max_shift_minutes=600,
        )
        db.session.add(plant)
        db.session.commit()
        print(f"Plant seeded: {plant.name} (id={plant.id})")
