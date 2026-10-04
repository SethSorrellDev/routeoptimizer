"""Retry behaviour of the identity-service client (no network, no sleeping)."""
import pytest
import requests

from app.auth import identity


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return {"error": "Bad credentials"}


def _script(monkeypatch, outcomes):
    """Replace requests.post. Each call consumes the next outcome (an int
    status or an exception); the last outcome repeats forever."""
    calls = []
    remaining = list(outcomes)

    def fake_post(url, json=None, timeout=None):
        calls.append(url)
        outcome = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    monkeypatch.setattr(identity.requests, "post", fake_post)
    return calls


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(identity.time, "sleep", slept.append)
    return slept


def test_first_attempt_success_does_not_sleep(monkeypatch, no_sleep):
    calls = _script(monkeypatch, [200])
    assert identity._post("/auth/login", {}).status_code == 200
    assert len(calls) == 1 and no_sleep == []


def test_retries_a_502_then_succeeds(monkeypatch, no_sleep):
    calls = _script(monkeypatch, [502, 200])
    assert identity._post("/auth/login", {}).status_code == 200
    assert len(calls) == 2 and no_sleep == [identity.RETRY_DELAY_SECONDS]


def test_retries_connection_errors_and_timeouts(monkeypatch, no_sleep):
    calls = _script(monkeypatch, [requests.ConnectionError(), requests.Timeout(), 200])
    assert identity._post("/auth/login", {}).status_code == 200
    assert len(calls) == 3


def test_gives_up_with_the_waking_message(monkeypatch, no_sleep):
    calls = _script(monkeypatch, [503])
    with pytest.raises(identity.IdentityError) as exc:
        identity._post("/auth/login", {})
    assert str(exc.value) == identity.WAKING_MESSAGE
    assert len(calls) == identity.ATTEMPTS
    assert len(no_sleep) == identity.ATTEMPTS - 1


@pytest.mark.parametrize("status", [400, 401, 409, 500])
def test_real_answers_are_not_retried(monkeypatch, no_sleep, status):
    calls = _script(monkeypatch, [status])
    assert identity._post("/auth/login", {}).status_code == status
    assert len(calls) == 1 and no_sleep == []


def test_bad_credentials_still_surface_the_service_message(monkeypatch, no_sleep):
    _script(monkeypatch, [400])
    with pytest.raises(identity.IdentityError, match="Bad credentials"):
        identity.authenticate("a@b.co", "wrong")
