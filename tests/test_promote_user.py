"""Tests for promote_user.py — the only path from SSR to Manager."""
from app.extensions import db
from app.models import Role, User
from promote_user import promote_to_manager
from seed_roles import seed_roles


def _make_ssr_user(email="driver@example.com", name="Driver"):
    seed_roles()
    ssr_role = Role.query.filter_by(name="SSR").first()
    user = User(name=name, username=email.split("@")[0], email=email, role_id=ssr_role.id)
    user.set_password("irrelevant-for-this-test")
    db.session.add(user)
    db.session.commit()
    return user


def test_promote_to_manager_changes_the_role(app):
    user = _make_ssr_user()
    manager_role = Role.query.filter_by(name="Manager").first()

    promoted, error = promote_to_manager(user.email)

    assert error is None
    assert promoted.role_id == manager_role.id


def test_promote_to_manager_is_case_insensitive_on_email(app):
    user = _make_ssr_user(email="Driver@Example.com")
    promoted, error = promote_to_manager("driver@example.com")
    assert error is None
    assert promoted.id == user.id


def test_promote_to_manager_is_idempotent(app):
    user = _make_ssr_user()
    promote_to_manager(user.email)
    promoted_again, error = promote_to_manager(user.email)
    assert error is None
    assert promoted_again.id == user.id


def test_promote_to_manager_reports_an_unknown_email(app):
    seed_roles()
    user, error = promote_to_manager("nobody@example.com")
    assert user is None
    assert "No local user found" in error


def test_promote_to_manager_requires_the_manager_role_to_exist(app):
    """Guards against running this before seed_roles.py."""
    ssr = Role(name="SSR")
    db.session.add(ssr)
    db.session.commit()

    user = User(name="Driver", username="driver", email="driver@example.com", role_id=ssr.id)
    user.set_password("irrelevant")
    db.session.add(user)
    db.session.commit()

    promoted, error = promote_to_manager(user.email)
    assert promoted is None
    assert "Manager role" in error
