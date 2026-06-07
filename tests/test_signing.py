"""Behavioural tests for the Deep Dive Link signing module.

These exercise the public interface as pure functions — the security boundary
of the Deep Dive feature. The batch handler signs links; the public trigger
verifies them. Both import this one module so the two can never drift apart.
"""

import pytest

import signing

SECRET = "test-signing-secret"


def test_sign_verify_round_trip_recovers_source_and_paper_id():
    token = signing.sign("IACR ePrint", "2024/123", SECRET)

    result = signing.verify(token, SECRET)

    assert result is not None
    assert result.source == "IACR ePrint"
    assert result.paper_id == "2024/123"


def test_tampered_token_is_rejected():
    token = signing.sign("IACR ePrint", "2024/123", SECRET)
    # Flip the last character of the payload portion to forge a different paper.
    payload_b64, _, mac_b64 = token.partition(".")
    forged = payload_b64[:-1] + ("A" if payload_b64[-1] != "A" else "B")
    tampered = f"{forged}.{mac_b64}"

    assert signing.verify(tampered, SECRET) is None


def test_token_signed_with_different_secret_is_rejected():
    token = signing.sign("IACR ePrint", "2024/123", "the-real-secret")

    assert signing.verify(token, "a-different-secret") is None


@pytest.mark.parametrize(
    "garbage",
    [
        "",                          # empty
        "no-separator-at-all",       # no '.' delimiter
        ".",                         # empty payload and mac
        "!!!not-base64!!!.@@@",      # invalid base64 alphabet
        "a.b",                       # decodable base64 but wrong-length mac
        "\x00\x01\x02.\x03",         # control bytes
    ],
)
def test_garbage_token_is_rejected_without_raising(garbage):
    assert signing.verify(garbage, SECRET) is None


def test_valid_paper_id_derives_domain_locked_pdf_url():
    assert signing.derive_pdf_url("2024/123") == "https://eprint.iacr.org/2024/123.pdf"


@pytest.mark.parametrize(
    "bad_id",
    [
        "",                                   # empty
        "2024",                               # missing /NNN
        "2024/",                              # missing number
        "/123",                               # missing year
        "24/123",                             # year not 4 digits
        "2024/12a",                           # non-digit in number
        "2024/123/456",                       # extra path segment
        "2024 123",                           # space instead of slash
        "../../etc/passwd",                   # path traversal
        "2024/../../secret",                  # traversal smuggled after a valid prefix
        "2024/123.pdf",                       # caller tries to inject the suffix
        "2024/123#fragment",                  # url fragment injection
        "2024/123?x=1",                       # query string injection
        "@evil.com/2024/123",                 # host override attempt
        "https://evil.com/2024/123",          # full url injection
        "2024/123\n2025/456",                 # newline / second value
    ],
)
def test_malformed_or_injection_paper_id_is_rejected(bad_id):
    assert signing.derive_pdf_url(bad_id) is None
