import pytest


@pytest.fixture(autouse=True)
def _fresh_auth_throttle():
    """Every test starts with an empty sign-in throttle (tests register many accounts)."""
    import webapp.backend.app as backend
    backend._attempts.clear()
    backend._stores.clear()                 # each test's USERS_DB gets its own store
    backend._search_store = None
    yield
