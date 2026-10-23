"""The booking UI: served same-origin, locked down by CSP, and written CSP-safe."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from tests.utils import TUE, WED

STATIC = Path(__file__).parents[1] / "app" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")


# ---- static checks (no server needed) -------------------------------------------


def test_page_has_no_inline_script_or_style() -> None:
    # The CSP allows only same-origin files, so inline code would be blocked anyway.
    # Case-insensitive: HTML tag and attribute names are (CodeQL py/bad-tag-filter).
    scripts = re.findall(r"<script\b([^>]*)>", HTML, re.IGNORECASE)
    assert scripts and all("src=" in attrs.lower() for attrs in scripts)
    assert "<style" not in HTML.lower()
    assert not re.search(r"\sstyle=", HTML, re.IGNORECASE)
    assert not re.search(r"\son[a-z]+=", HTML, re.IGNORECASE)  # no inline event handlers


def test_script_never_parses_html_from_strings() -> None:
    # All API and user text goes in via textContent/createElement (XSS-safe).
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert sink not in JS, sink


def test_assets_are_local() -> None:
    assert not re.search(r"""(src|href)=["']https?://""", HTML, re.IGNORECASE)
    assert "url(http" not in (STATIC / "app.css").read_text(encoding="utf-8")


def test_font_licence_ships_with_the_font() -> None:
    assert (STATIC / "atkinson-next-latin.woff2").read_bytes()[:4] == b"wOF2"
    assert "SIL Open Font License" in (STATIC / "OFL-atkinson-hyperlegible-next.txt").read_text(
        encoding="utf-8"
    )


def test_forms_never_submit_via_get() -> None:
    # Found by ZAP (10024): without JS a GET form would put the email and password in
    # the URL (history, logs, Referer). POST to / is a harmless 405 instead.
    forms = re.findall(r"<form\b([^>]*)>", HTML, re.IGNORECASE)
    assert forms and all('method="post"' in attrs.lower() for attrs in forms)


def test_verify_link_needs_a_click() -> None:
    # Opening an emailed link must not act by itself (link scanners, links from others).
    assert 'id="verify-confirm"' in HTML
    route = JS[JS.index("async function route()") : JS.index("// ---- booking")]
    assert "/auth/verify" not in route and "confirmEmail" not in route


# ---- served by the app ---------------------------------------------------------


def test_index_is_served_with_a_strict_csp(anon: TestClient) -> None:
    r = anon.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    csp = r.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cross-Origin-Embedder-Policy"] == "require-corp"


def test_no_js_form_post_to_index_leaks_nothing(anon: TestClient) -> None:
    r = anon.post("/", data={"email": "a@example.com", "password": "secret value 123"})
    assert r.status_code == 405
    assert "secret value" not in r.text


def test_assets_are_served(anon: TestClient) -> None:
    js = anon.get("/assets/app.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert anon.get("/assets/app.css").status_code == 200
    assert anon.get("/assets/atkinson-next-latin.woff2").status_code == 200


def test_no_path_traversal_out_of_assets(anon: TestClient) -> None:
    for path in ("/assets/../main.py", "/assets/%2e%2e/main.py", "/assets/..%2fmain.py"):
        r = anon.get(path)
        assert r.status_code == 404, path
        assert "create_app" not in r.text


def test_availability_includes_working_hours_for_the_day_strip(anon: TestClient) -> None:
    body = anon.get("/doctors/1/availability", params={"date": TUE}).json()
    assert body["working_hours"] == ["08:00-12:00", "13:00-17:00"]
    day_off = anon.get("/doctors/4/availability", params={"date": WED}).json()
    assert day_off["working_hours"] == [] and day_off["slots"] == []
