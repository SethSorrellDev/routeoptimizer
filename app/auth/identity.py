"""Client for the shared identity-service.

Flask-Login keeps owning the browser session. This module only answers two
questions: "did identity-service accept this email and password?" and "who
does the signed token say this is?". The token is verified against the
service's public JWKS, so RouteOptimizer never holds a private key.
"""
import os

import jwt
import requests
from jwt import PyJWKClient

TIMEOUT_SECONDS = 5


class IdentityError(Exception):
    """Sign-in failed. The message is safe to show to the user."""


def _base_url():
    return os.environ.get("IDENTITY_URL", "http://localhost:8081").rstrip("/")


def _issuer():
    return os.environ.get("IDENTITY_ISSUER", "identity-service")


_jwks_client = None
_jwks_url = None


def _signing_key(token):
    """Look up the key for this token's kid. PyJWKClient caches the key set
    and refetches once if it sees a kid it doesn't know (key rotation)."""
    global _jwks_client, _jwks_url
    url = f"{_base_url()}/.well-known/jwks.json"
    if _jwks_client is None or _jwks_url != url:
        _jwks_client = PyJWKClient(url, cache_keys=True, timeout=TIMEOUT_SECONDS)
        _jwks_url = url
    return _jwks_client.get_signing_key_from_jwt(token).key


def verify_access_token(token):
    """Return the claims of a valid identity-service ACCESS token.

    Checks signature (RS256 only), expiry, issuer, and that this is an access
    token. Refresh tokens carry the same signature, so the "type" claim check
    is what stops one being used as the other.
    """
    try:
        claims = jwt.decode(
            token,
            _signing_key(token),
            algorithms=["RS256"],
            issuer=_issuer(),
            options={"require": ["exp", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise IdentityError("Could not verify the sign-in token.") from exc

    if claims.get("type") != "access":
        raise IdentityError("Could not verify the sign-in token.")
    return claims


def authenticate(email, password):
    """Sign in against identity-service and return verified access-token claims.

    Raises IdentityError with a user-safe message on any failure.
    """
    try:
        response = requests.post(
            f"{_base_url()}/auth/login",
            json={"email": email, "password": password},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise IdentityError("The sign-in service is unavailable. Try again shortly.") from exc

    if response.status_code == 400:
        # Identity-service answers bad credentials with 400 and {"error": "..."}.
        try:
            message = response.json().get("error") or "Invalid email or password."
        except ValueError:
            message = "Invalid email or password."
        raise IdentityError(message)

    if not response.ok:
        raise IdentityError("The sign-in service returned an error. Try again shortly.")

    try:
        access_token = response.json()["accessToken"]
    except (ValueError, KeyError) as exc:
        raise IdentityError("The sign-in service returned an unexpected response.") from exc

    return verify_access_token(access_token)
