"""Behavioural tests for Deep Dive link generation in the Digest."""

import os
import pytest

import handler
from handler import AnalyzedRecord, Record


def _make_analyzed(url: str = "https://eprint.iacr.org/2024/123") -> AnalyzedRecord:
    return AnalyzedRecord(
        record=Record(
            title="Test Paper",
            abstract="An abstract.",
            subjects=["Cryptography"],
            published_date="2024-01-01",
            authors=["Alice"],
            url=url,
        ),
        score=8,
        summary="Very relevant.",
    )


# ---------------------------------------------------------------------------
# _build_paper_html
# ---------------------------------------------------------------------------

def test_build_paper_html_includes_deep_dive_link_when_url_provided():
    ar = _make_analyzed()
    html = handler._build_paper_html(ar, deep_dive_url="https://trigger.example.com/?token=abc123")

    assert "Request a deep dive" in html
    assert "https://trigger.example.com/?token=abc123" in html


def test_build_paper_html_omits_deep_dive_markup_when_url_is_none():
    ar = _make_analyzed()
    html = handler._build_paper_html(ar, deep_dive_url=None)

    assert "deep-dive" not in html
    assert "Request a deep dive" not in html


# ---------------------------------------------------------------------------
# _build_digest — link generation
# ---------------------------------------------------------------------------

def test_build_digest_includes_signed_deep_dive_link_per_paper(monkeypatch):
    monkeypatch.setenv("DEEP_DIVE_BASE_URL", "https://trigger.example.com/")
    monkeypatch.setenv("DEEP_DIVE_SIGNING_SECRET", "test-secret")

    ar = _make_analyzed()
    html = handler._build_digest([ar], threshold=7)

    assert "Request a deep dive" in html
    assert "token=" in html


def test_build_digest_omits_deep_dive_link_when_base_url_absent(monkeypatch):
    monkeypatch.delenv("DEEP_DIVE_BASE_URL", raising=False)
    monkeypatch.setenv("DEEP_DIVE_SIGNING_SECRET", "test-secret")

    ar = _make_analyzed()
    html = handler._build_digest([ar], threshold=7)

    assert html  # renders without crashing
    assert "Request a deep dive" not in html
    assert "token=" not in html


# ---------------------------------------------------------------------------
# _build_digest — warning on missing deep dive links
# ---------------------------------------------------------------------------

def test_build_digest_warns_once_when_deep_dive_config_missing(monkeypatch, caplog):
    monkeypatch.delenv("DEEP_DIVE_BASE_URL", raising=False)
    monkeypatch.setenv("DEEP_DIVE_SIGNING_SECRET", "test-secret")

    with caplog.at_level("WARNING", logger=handler.logger.name):
        handler._build_digest([_make_analyzed(), _make_analyzed()], threshold=7)

    config_warnings = [
        r for r in caplog.records
        if r.levelname == "WARNING" and "DEEP_DIVE_BASE_URL" in r.getMessage()
    ]
    assert len(config_warnings) == 1  # warned once for the digest, not per paper


def test_build_digest_warns_per_paper_when_url_unrecognized(monkeypatch, caplog):
    monkeypatch.setenv("DEEP_DIVE_BASE_URL", "https://trigger.example.com/")
    monkeypatch.setenv("DEEP_DIVE_SIGNING_SECRET", "test-secret")

    ar = _make_analyzed(url="https://example.com/not-iacr")

    with caplog.at_level("WARNING", logger=handler.logger.name):
        html = handler._build_digest([ar], threshold=7)

    assert "Request a deep dive" not in html
    paper_warnings = [
        r for r in caplog.records
        if r.levelname == "WARNING" and "https://example.com/not-iacr" in r.getMessage()
    ]
    assert len(paper_warnings) == 1
