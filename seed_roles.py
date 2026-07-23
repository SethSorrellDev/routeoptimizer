from app import create_app
from app.extensions import db
from app.models import Role

app = create_app()
with app.app_context():
    existing = {r.name for r in Role.query.all()}
    for name in ("Manager", "SSR"):
        if name not in existing:
            db.session.add(Role(name=name))
    db.session.commit()
    print("Roles in DB:", [r.name for r in Role.query.all()])
