"""Minimal fixed-window rate limiter on Django's local-memory cache.

No external dependency, no extra service. Per-process (see CACHES note in
settings): exact with one gunicorn worker; with N workers the effective limit
is N times higher — still bounded, which is all the abuse mitigation needs.
"""

import time

from django.core.cache import cache

# Generous for humans (one save per modal confirm), tight for scripts.
PREDICTION_RATE_LIMIT = (20, 60)  # max requests, window seconds
# Shared by the site login view and the admin login (same key, one budget).
LOGIN_RATE_LIMIT = (10, 300)


def is_rate_limited(key, max_requests, window_seconds):
    """True when `key` exceeded `max_requests` within the current window."""
    window = int(time.time() // window_seconds)
    cache_key = f"throttle:{key}:{window}"

    # add() is atomic: returns False when the key already exists.
    if cache.add(cache_key, 1, timeout=window_seconds):
        return False

    try:
        count = cache.incr(cache_key)
    except ValueError:  # expired between add() and incr()
        cache.add(cache_key, 1, timeout=window_seconds)
        return False
    return count > max_requests


def client_ip(request):
    """Client IP, honoring Railway's proxy header when present.

    Proxies APPEND the address they received the request from, so the LAST
    entry is the one Railway's edge wrote — trustworthy. Earlier entries are
    client-supplied and spoofable; using them would let an attacker rotate
    fake IPs to bypass the login throttle.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "unknown")
