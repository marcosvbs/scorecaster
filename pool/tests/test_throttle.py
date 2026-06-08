import time
from types import SimpleNamespace

from pool.services.throttle import client_ip, is_rate_limited


def test_allows_up_to_max_requests():
    for _ in range(5):
        assert is_rate_limited("k1", 5, 60) is False

    assert is_rate_limited("k1", 5, 60) is True


def test_keys_are_independent():
    for _ in range(5):
        is_rate_limited("user-a", 5, 60)
    assert is_rate_limited("user-a", 5, 60) is True

    assert is_rate_limited("user-b", 5, 60) is False


def test_limit_resets_on_next_window(monkeypatch):
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)
    for _ in range(3):
        is_rate_limited("k2", 3, 60)
    assert is_rate_limited("k2", 3, 60) is True

    monkeypatch.setattr(time, "time", lambda: now + 61)
    assert is_rate_limited("k2", 3, 60) is False


def test_expiry_race_between_add_and_incr(monkeypatch):
    """Key expiring between add() and incr() must not 500 — counts as fresh."""
    from pool.services import throttle

    monkeypatch.setattr(throttle.cache, "add", lambda *a, **k: False)

    def raise_value_error(key):
        raise ValueError("key gone")

    monkeypatch.setattr(throttle.cache, "incr", raise_value_error)

    assert is_rate_limited("race-key", 5, 60) is False


def make_request(meta):
    return SimpleNamespace(META=meta)


def test_client_ip_prefers_forwarded_header():
    # The LAST entry is the one the trusted proxy appended.
    request = make_request(
        {"HTTP_X_FORWARDED_FOR": "10.0.0.1, 203.0.113.7", "REMOTE_ADDR": "10.0.0.1"}
    )
    assert client_ip(request) == "203.0.113.7"


def test_client_ip_ignores_spoofed_forwarded_entries():
    """Client-supplied XFF entries come first; only the proxy-appended last
    entry counts, so rotating fake IPs cannot dodge the login throttle."""
    real_ip = "203.0.113.7"
    for fake in ("1.2.3.4", "5.6.7.8", "9.10.11.12"):
        request = make_request(
            {"HTTP_X_FORWARDED_FOR": f"{fake}, {real_ip}", "REMOTE_ADDR": "10.0.0.1"}
        )
        assert client_ip(request) == real_ip


def test_client_ip_falls_back_to_remote_addr():
    assert client_ip(make_request({"REMOTE_ADDR": "192.0.2.1"})) == "192.0.2.1"
    assert client_ip(make_request({})) == "unknown"
