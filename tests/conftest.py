import pytest


@pytest.fixture(autouse=True)
def _fresh_auth_throttle():
    """Every test starts with an empty sign-in throttle (tests register many accounts)."""
    import webapp.backend.app as backend
    backend._attempts.clear()
    yield
