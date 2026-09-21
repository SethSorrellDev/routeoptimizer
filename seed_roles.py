"""Seed the two application roles. Safe to re-run."""
from app.extensions import db
from app.models import Role

ROLE_NAMES = ("Manager", "SSR")


def seed_roles():
    """Create any missing roles. Returns the list of names created."""
    existing = {r.name for r in Role.query.all()}
    created = []
    for name in ROLE_NAMES:
        if name not in existing:
            db.session.add(Role(name=name))
            created.append(name)
    if created:
        db.session.commit()
    return created


if __name__ == "__main__":
    from app import create_app

    app = create_app()
    with app.app_context():
        created = seed_roles()
        print("Created:", ", ".join(created) if created else "nothing (already present)")
        print("Roles in DB:", [r.name for r in Role.query.order_by(Role.name).all()])
