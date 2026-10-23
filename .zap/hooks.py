"""ZAP API-scan hooks (loaded with --hook).

Logging out would revoke the scan's own bearer token and turn the rest of the
scan into 401s (seen on the first run: 1,333 of 3,188 requests were 401 after a
single POST /auth/logout). Logout itself is covered by tests/security.

The booking UI (HTML/CSS/JS/fonts at / and /assets/) is not part of the API: the
API scan's "unexpected content type" rule (100001) flags it. zap-baseline.py
scans the UI page separately in scripts/zap_scan.sh.
"""

LOGOUT = r".*/auth/logout.*"
UI = r"^https?://[^/]+/(\?.*)?$|.*/assets/.*"


def zap_started(zap, target):
    for pattern in (LOGOUT, UI):
        zap.core.exclude_from_proxy(pattern)
        zap.spider.exclude_from_scan(pattern)
        zap.ascan.exclude_from_scan(pattern)
