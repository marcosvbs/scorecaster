from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _pin_throttle_window():
    """Freeze the rate limiter's clock for every test in this module.

    The limiter buckets by a fixed window: ``int(time.time() // window)``.
    A burst of 10+ attempts that happens to straddle a 300s boundary lands in
    two buckets, resetting the counter — so the Nth attempt slips through as
    200 instead of the expected 429. That made these tests flaky on CI. Pinning
    the clock keeps every attempt in one window without touching production.
    """
    with patch("pool.services.throttle.time.time", return_value=1_000_000.0):
        yield


def attempt_login(client, ip="198.51.100.1"):
    return client.post(
        "/login/",
        {"username": "nobody", "password": "wrong"},
        REMOTE_ADDR=ip,
    )


def test_login_blocked_after_limit(client, user):
    for _ in range(10):
        resp = attempt_login(client)
        assert resp.status_code == 200  # form re-rendered with error

    resp = attempt_login(client)
    assert resp.status_code == 429
    # Plain form POST: the throttle answer is the rendered login page with a
    # pt-BR message, not raw JSON.
    assert resp["Content-Type"].startswith("text/html")
    assert "Muitas tentativas de login" in resp.content.decode()


def test_login_throttle_is_per_ip(client, user):
    for _ in range(10):
        attempt_login(client, ip="198.51.100.1")
    assert attempt_login(client, ip="198.51.100.1").status_code == 429

    assert attempt_login(client, ip="198.51.100.2").status_code == 200


def test_successful_login_within_limit_still_works(client, user):
    for _ in range(3):
        attempt_login(client)

    resp = client.post(
        "/login/",
        {"username": "rafael", "password": "test123"},
        REMOTE_ADDR="198.51.100.1",
    )
    assert resp.status_code == 302  # redirected home


def attempt_admin_login(client, ip="198.51.100.1"):
    return client.post(
        "/admin/login/",
        {"username": "nobody", "password": "wrong"},
        REMOTE_ADDR=ip,
    )


def test_admin_login_blocked_after_limit(client, user):
    for _ in range(10):
        resp = attempt_admin_login(client)
        assert resp.status_code == 200  # admin form re-rendered with error

    resp = attempt_admin_login(client)
    assert resp.status_code == 429


def test_admin_and_site_login_share_one_budget(client, user):
    """Same throttle key for both forms: 10 attempts total per IP, not 10
    on each."""
    for _ in range(5):
        attempt_login(client)
    for _ in range(5):
        attempt_admin_login(client)

    assert attempt_login(client).status_code == 429
    assert attempt_admin_login(client).status_code == 429


def test_admin_login_get_is_not_throttled(client, user):
    for _ in range(11):
        attempt_admin_login(client)
    assert attempt_admin_login(client).status_code == 429

    # GETs (rendering the form) stay available even while POSTs are blocked.
    assert client.get("/admin/login/", REMOTE_ADDR="198.51.100.1").status_code == 200


def test_login_throttle_ignores_spoofed_forwarded_header(client, user):
    """Rotating fake first XFF entries must not reset the budget — only the
    proxy-appended last entry identifies the client."""
    for i in range(10):
        client.post(
            "/login/",
            {"username": "nobody", "password": "wrong"},
            REMOTE_ADDR="10.0.0.1",
            HTTP_X_FORWARDED_FOR=f"1.2.3.{i}, 203.0.113.7",
        )

    resp = client.post(
        "/login/",
        {"username": "nobody", "password": "wrong"},
        REMOTE_ADDR="10.0.0.1",
        HTTP_X_FORWARDED_FOR="9.9.9.9, 203.0.113.7",
    )
    assert resp.status_code == 429
