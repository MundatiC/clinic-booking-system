"""Email templates: `templates/<name>.txt` (first line `Subject: ...`) + `<name>.html`.

Every value is HTML-escaped before it reaches the HTML part; the text part is
plain text, so it needs no escaping. Header injection is blocked by the stdlib
email policy (it rejects CR/LF in header values).
"""

from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import parseaddr
from functools import cache
from html import escape
from pathlib import Path
from string import Template

_DIR = Path(__file__).parent / "templates"


@cache
def _load(filename: str) -> Template:
    return Template((_DIR / filename).read_text(encoding="utf-8"))


def render(template: str, /, *, to: str, sender: str, clinic: str, **values: str) -> EmailMessage:
    subject_line, text_body = _load(f"{template}.txt").template.split("\n", 1)
    plain = {"clinic": clinic, **values}
    subject = Template(subject_line.removeprefix("Subject: ")).substitute(plain)
    escaped = {k: escape(v, quote=True) for k, v in plain.items()}
    html_body = _load(f"{template}.html").substitute(escaped)
    html = _load("base.html").substitute(
        subject=escape(subject), clinic=escaped["clinic"], body=html_body
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    display, address = parseaddr(to)
    message["To"] = Address(display, addr_spec=address)
    message.set_content(Template(text_body.strip()).substitute(plain) + "\n")
    message.add_alternative(html, subtype="html")
    return message
