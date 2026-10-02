"""SSO login and token verification.

identity-service is never contacted: tokens are signed with a throwaway key and
the network call is patched out.
"""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import identity
from app.models import Role, User
from seed_roles import seed_roles

SUB = "11111111-1111-1111-1111-111111111111"
EMAIL = "sso.user@sample.org"


@pytest.fixture(scope="module")
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(key, algorithm="RS256", **overrides):
    now = int(time.time())
    claims = {"sub": SUB, "iss": "identity-service", "type": "access",
              "email": EMAIL, "iat": now, "exp": now + 900}
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm=algorithm)


@pytest.fixture
def verifier(monkeypatch, private_key):
    monkeypatch.setattr(identity, "_signing_key", lambda token: private_key.public_key())
    return private_key


# ---- token verification ---------------------------------------------------

def test_valid_access_token_is_accepted(verifier):
    claims = identity.verify_access_token(make_token(verifier))
    assert claims["sub"] == SUB


def test_refresh_token_is_rejected(verifier):
    with pytest.raises(identity.IdentityError):
        identity.verify_access_token(make_token(verifier, type="refresh"))


def test_wrong_issuer_is_rejected(verifier):
    with pytest.raises(identity.IdentityError):
        identity.verify_access_token(make_token(verifier, iss="someone-else"))


def test_expired_token_is_rejected(verifier):
    with pytest.raises(identity.IdentityError):
        identity.verify_access_token(make_token(verifier, exp=int(time.time()) - 10))


def test_token_signed_with_a_different_key_is_rejected(verifier):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(identity.IdentityError):
        identity.verify_access_token(make_token(other))


def test_hs256_token_is_rejected(verifier):
    # Algorithm-confusion guard: only RS256 is ever accepted.
    with pytest.raises(identity.IdentityError):
        identity.verify_access_token(make_token("x" * 64, algorithm="HS256"))


# ---- login view -----------------------------------------------------------

@pytest.fixture
def client(app):
    seed_roles()
    return app.test_client()


def fake_identity(monkeypatch, sub=SUB, email=EMAIL):
    monkeypatch.setattr(identity, "authenticate", lambda e, p: {"sub": sub, "email": email})


def post_login(client, email=EMAIL, password="testpass123"):
    return client.post("/auth/login", data={"email": email, "password": password})


def logged_in_user_id(client):
    with client.session_transaction() as s:
        return s.get("_user_id")


def create_local(db, email=EMAIL, password="testpass123", sub=None, role="SSR"):
    user = User(name="Local", username=email.split("@")[0], email=email,
                role_id=Role.query.filter_by(name=role).first().id, identity_sub=sub)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def test_new_identity_user_is_provisioned_as_ssr(client, db, monkeypatch):
    fake_identity(monkeypatch)
    response = post_login(client)
    assert response.status_code == 302
    db.session.expire_all()
    user = User.query.filter_by(identity_sub=SUB).one()
    assert user.role.name == "SSR"
    assert logged_in_user_id(client) == str(user.id)


def test_existing_local_user_is_linked_when_local_password_matches(client, db, monkeypatch):
    local = create_local(db, password="testpass123")
    fake_identity(monkeypatch)
    assert post_login(client, password="testpass123").status_code == 302
    db.session.expire_all()
    assert db.session.get(User, local.id).identity_sub == SUB
    assert User.query.count() == 1  # linked, not duplicated


def test_existing_local_user_is_not_linked_when_local_password_differs(client, db, monkeypatch):
    local = create_local(db, password="the-real-local-password")
    fake_identity(monkeypatch)  # identity accepts "testpass123" for this email
    response = post_login(client, password="testpass123")
    assert response.status_code == 200
    assert b"existing RouteOptimizer password" in response.data
    db.session.expire_all()
    assert db.session.get(User, local.id).identity_sub is None
    assert logged_in_user_id(client) is None


def test_returning_user_is_matched_by_sub(client, db, monkeypatch):
    local = create_local(db, email="old.email@sample.org", sub=SUB)
    fake_identity(monkeypatch, email="new.email@sample.org")  # email changed in identity
    assert post_login(client, email="new.email@sample.org").status_code == 302
    assert logged_in_user_id(client) == str(local.id)


def test_account_linked_to_another_identity_is_refused(client, db, monkeypatch):
    create_local(db, sub="22222222-2222-2222-2222-222222222222")
    fake_identity(monkeypatch)
    response = post_login(client)
    assert response.status_code == 200
    assert b"already linked" in response.data
    assert logged_in_user_id(client) is None


def test_identity_rejection_does_not_log_in(client, monkeypatch):
    def reject(email, password):
        raise identity.IdentityError("Invalid email or password")
    monkeypatch.setattr(identity, "authenticate", reject)
    response = post_login(client, password="wrong")
    assert response.status_code == 200
    assert b"Invalid email or password" in response.data
    assert logged_in_user_id(client) is None


# ---- registration ---------------------------------------------------------

def post_register(client, name="Pat Doe", email=EMAIL, password="testpass123", confirm=None):
    return client.post("/auth/register", data={
        "name": name, "email": email, "password": password,
        "confirm": confirm if confirm is not None else password,
    })


def test_registration_creates_an_ssr_and_logs_in(client, db, monkeypatch):
    monkeypatch.setattr(identity, "register", lambda n, e, p: {"sub": SUB, "email": e})
    response = post_register(client)
    assert response.status_code == 302
    db.session.expire_all()
    user = User.query.filter_by(identity_sub=SUB).one()
    assert user.role.name == "SSR"
    assert user.name == "Pat Doe"
    assert logged_in_user_id(client) == str(user.id)


def test_registration_cannot_choose_a_role(client, db, monkeypatch):
    monkeypatch.setattr(identity, "register", lambda n, e, p: {"sub": SUB, "email": e})
    post_register(client)  # even a forged "role" field is ignored
    client.get("/auth/logout")
    client.post("/auth/register", data={"name": "X Y", "email": "x@y.org", "password": "testpass123",
                                         "confirm": "testpass123", "role": "Manager"})
    assert all(u.role.name == "SSR" for u in User.query.all())


def test_registration_surfaces_identity_errors(client, db, monkeypatch):
    def reject(n, e, p):
        raise identity.IdentityError("Email already registered")
    monkeypatch.setattr(identity, "register", reject)
    response = post_register(client)
    assert response.status_code == 200
    assert b"Email already registered" in response.data
    assert User.query.count() == 0
    assert logged_in_user_id(client) is None


def test_registration_rejects_mismatched_passwords_without_calling_identity(client, monkeypatch):
    def boom(n, e, p):
        raise AssertionError("identity-service must not be called")
    monkeypatch.setattr(identity, "register", boom)
    response = post_register(client, confirm="different-password")
    assert response.status_code == 200
    assert logged_in_user_id(client) is None
