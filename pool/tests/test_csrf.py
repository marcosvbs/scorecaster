from django.test import Client


def test_login_page_is_never_cached(client):
    """The login form must carry no-store so a stale, cached form (back button /
    bfcache) can't POST an outdated CSRF token after login rotates it."""
    resp = client.get("/login/")

    assert resp.status_code == 200
    assert "no-store" in resp.headers.get("Cache-Control", "")


def test_csrf_failure_renders_friendly_login(db):
    """A POST with no CSRF token hits CSRF_FAILURE_VIEW -> friendly pt-BR login
    page (403) with a fresh token, not the raw Django 403."""
    csrf_client = Client(enforce_csrf_checks=True)

    resp = csrf_client.post("/login/", {"username": "x", "password": "y"})

    assert resp.status_code == 403
    body = resp.content.decode()
    assert "Sua sessão expirou" in body
    assert 'name="username"' in body  # the login form is re-rendered
    assert "csrftoken" in resp.cookies  # a fresh token is issued for the retry
