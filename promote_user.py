"""Promote an existing local user to the Manager role.

Registration always provisions new accounts as SSR (the least-privileged
role) — there is no signup path to Manager, by design, since identity-service
has no concept of roles at all; RouteOptimizer owns that entirely. This script
is the one way to create a Manager account: register normally through the
app first, then run this against that email.

    python promote_user.py someone@example.com
"""
import sys

from app.extensions import db
from app.models import Role, User


def promote_to_manager(email):
    """Set the given user's role to Manager. Returns (user, error_message).

    error_message is None on success, otherwise a human-readable reason and
    user is None.
    """
    user = User.query.filter(db.func.lower(User.email) == email.strip().lower()).first()
    if user is None:
        return None, f"No local user found with email {email!r}."

    manager_role = Role.query.filter_by(name="Manager").first()
    if manager_role is None:
        return None, "No Manager role found — run seed_roles.py first."

    if user.role_id == manager_role.id:
        return user, None  # already a manager; nothing to do

    user.role_id = manager_role.id
    db.session.commit()
    return user, None


if __name__ == "__main__":
    from app import create_app

    if len(sys.argv) != 2:
        print("Usage: python promote_user.py <email>")
        sys.exit(1)

    app = create_app()
    with app.app_context():
        user, error = promote_to_manager(sys.argv[1])
        if error:
            print(f"Error: {error}")
            sys.exit(1)
        print(f"{user.name} ({user.email}) is now a Manager.")
