"""Deep Dive Link signing — the security core shared by the batch handler
(which generates signed links) and the public trigger (which verifies them).

The token signs only ``{source, paper_id}``; nothing stale or expiring is frozen
into it. The PDF URL is derived deterministically from a signed ``paper_id`` so
the worker's fetch is locked to the Source domain — no caller-supplied URL is
ever trusted (the structural SSRF guarantee).

All functions are pure and side-effect-free. Rejection is signalled by
returning ``None``; no exceptions leak through to callers.
"""

import base64
import binascii
import hashlib
import hmac
import re
from typing import NamedTuple, Optional


class SignedPaper(NamedTuple):
    source: str
    paper_id: str


# Field separator inside the signed payload — a unit-separator control byte that
# cannot appear in a source name or paper id.
_SEP = "\x1f"

# An IACR ePrint paper id is exactly ``YYYY/NNN``: a four-digit year, a slash,
# and a run of digits. ``fullmatch`` anchors both ends, so nothing can be
# smuggled before or after — no path traversal, no URL fragment/query, no host
# override, no second value on a new line. This is the structural SSRF guard:
# the only URL we ever build comes from an id matching this shape.
_PAPER_ID_RE = re.compile(r"\d{4}/\d+")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def sign(source: str, paper_id: str, secret: str) -> str:
    payload = f"{source}{_SEP}{paper_id}".encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_b64encode(payload)}.{_b64encode(mac)}"


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify(token: str, secret: str) -> Optional[SignedPaper]:
    payload_b64, sep, mac_b64 = token.partition(".")
    if not sep:
        return None
    try:
        payload = _b64decode(payload_b64)
        presented_mac = _b64decode(mac_b64)
    except (ValueError, binascii.Error):
        return None

    expected_mac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(presented_mac, expected_mac):
        return None

    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None

    source, _, paper_id = decoded.partition(_SEP)
    return SignedPaper(source=source, paper_id=paper_id)


def derive_pdf_url(paper_id: str) -> Optional[str]:
    if not _PAPER_ID_RE.fullmatch(paper_id):
        return None
    return f"https://eprint.iacr.org/{paper_id}.pdf"
