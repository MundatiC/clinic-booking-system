"""ZAP scan hooks (loaded with --hook).

Logging out would revoke the scan's own bearer token and turn the rest of the
scan into 401s (seen on the first run: 1,333 of 3,188 requests were 401 after a
single POST /auth/logout). Logout itself is covered by tests/security.
"""

LOGOUT = r".*/auth/logout.*"


def zap_started(zap, target):
    zap.core.exclude_from_proxy(LOGOUT)
    zap.spider.exclude_from_scan(LOGOUT)
    zap.ascan.exclude_from_scan(LOGOUT)
