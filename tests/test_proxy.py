"""Client IPs behind Render: a forged X-Forwarded-For must not pick the IP (audit 1)."""

import asyncio
import re
from pathlib import Path

from starlette.types import Message, Receive, Scope, Send
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

RENDER = (Path(__file__).parents[1] / "render.yaml").read_text(encoding="utf-8")


def _render_trusted_proxies() -> str:
    match = re.search(r'key: FORWARDED_ALLOW_IPS\s+value: "([^"]+)"', RENDER)
    assert match, "FORWARDED_ALLOW_IPS missing from render.yaml"
    return match.group(1)


def _client_seen(trusted: str, peer: str, forwarded_for: str) -> str:
    seen: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["client"][0])

    async def receive() -> Message:
        return {"type": "http.request"}

    async def send(message: Message) -> None:
        return None

    scope = {
        "type": "http",
        "client": (peer, 1234),
        "headers": [(b"x-forwarded-for", forwarded_for.encode())],
    }
    asyncio.run(ProxyHeadersMiddleware(app, trusted_hosts=trusted)(scope, receive, send))
    return seen[0]


def test_forged_forwarded_for_does_not_choose_the_client_ip() -> None:
    # The client writes the first entry; Render's private proxy appends the real one.
    trusted = _render_trusted_proxies()
    assert _client_seen(trusted, "10.1.2.3", "1.2.3.4, 203.0.113.9") == "203.0.113.9"


def test_trusting_everyone_would_take_the_forged_entry() -> None:
    # Why "*" was replaced: it reads the client-written first entry.
    assert _client_seen("*", "10.1.2.3", "1.2.3.4, 203.0.113.9") == "1.2.3.4"
