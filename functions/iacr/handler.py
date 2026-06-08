"""IACR ePrint Lambda handler — fetches papers via OAI-PMH, scores and summarizes
via Bedrock, and sends an HTML digest via SES."""

import asyncio
import logging
import os
import defusedxml.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, cast

import boto3
import httpx
from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel

import signing

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# OAI-PMH namespaces
_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}

IACR_OAI_ENDPOINT = "https://eprint.iacr.org/oai"
SOURCE_NAME = "IACR ePrint"
LOOKBACK_DAYS = 8
SSM_PREFIX = "/llm-rss/iacr"

TEMPLATE_PATH = Path(__file__).parent / "templates" / "digest.html"

_signing_secret_cache: Optional[str] = None


def _get_signing_secret() -> Optional[str]:
    global _signing_secret_cache
    if _signing_secret_cache:
        return _signing_secret_cache
    direct = os.environ.get("DEEP_DIVE_SIGNING_SECRET")
    if direct:
        _signing_secret_cache = direct
        return _signing_secret_cache
    param_name = os.environ.get("DEEP_DIVE_SIGNING_SECRET_PARAM")
    if not param_name:
        return None
    ssm = boto3.client("ssm")
    resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
    _signing_secret_cache = resp["Parameter"]["Value"]
    return _signing_secret_cache


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

class Record(BaseModel):
    title: str
    abstract: str
    subjects: list[str]
    published_date: str
    authors: list[str]
    url: str


class RecordAnalysis(BaseModel):
    score: int
    summary: str


class AnalyzedRecord(BaseModel):
    record: Record
    score: int
    summary: str


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _get_ssm_params() -> dict:
    ssm = boto3.client("ssm")
    names = [
        f"{SSM_PREFIX}/interest",
        f"{SSM_PREFIX}/threshold",
        f"{SSM_PREFIX}/bedrock-model-id",
        "/llm-rss/recipient-email",
    ]
    response = ssm.get_parameters(Names=names, WithDecryption=True)
    return {p["Name"]: p["Value"] for p in response["Parameters"]}


# ---------------------------------------------------------------------------
# OAI-PMH ingestion
# ---------------------------------------------------------------------------

def _date_range() -> tuple[str, str]:
    until = date.today()
    from_ = until - timedelta(days=LOOKBACK_DAYS)
    return from_.isoformat(), until.isoformat()


def _parse_records(xml_text: str) -> list[Record]:
    root = ET.fromstring(xml_text)
    records = []
    for item in root.findall(".//oai:record", _NS):
        header = item.find("oai:header", _NS)
        if header is not None and header.get("status") == "deleted":
            continue
        metadata = item.find(".//oai_dc:dc", _NS)
        if metadata is None:
            continue

        _meta = metadata

        def _texts(tag: str) -> list[str]:
            return [el.text.strip() for el in _meta.findall(f"dc:{tag}", _NS) if el.text]

        titles = _texts("title")
        descriptions = _texts("description")
        subjects = _texts("subject")
        dates = _texts("date")
        creators = _texts("creator")
        identifiers = _texts("identifier")

        if not titles or not descriptions:
            continue

        url = next((i for i in identifiers if i.startswith("https://")), "")
        records.append(Record(
            title=titles[0],
            abstract=descriptions[0],
            subjects=subjects,
            published_date=dates[0] if dates else "",
            authors=creators,
            url=url,
        ))
    return records


def fetch_records() -> list[Record]:
    from_, until = _date_range()
    params = {
        "verb": "ListRecords",
        "metadataPrefix": "oai_dc",
        "from": from_,
        "until": until,
    }
    all_records: list[Record] = []

    with httpx.Client(timeout=30) as client:
        while True:
            response = client.get(IACR_OAI_ENDPOINT, params=params)
            response.raise_for_status()
            records = _parse_records(response.text)
            all_records.extend(records)

            # Handle OAI-PMH resumption token for paginated results
            root = ET.fromstring(response.text)
            token_el = root.find(".//oai:resumptionToken", _NS)
            token_text = (token_el.text or "").strip() if token_el is not None else ""
            if not token_text:
                break
            params = {"verb": "ListRecords", "resumptionToken": token_text}

    logger.info("Fetched %d records from %s to %s", len(all_records), from_, until)
    return all_records


# ---------------------------------------------------------------------------
# LLM analysis
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a research assistant helping a user track academic papers relevant to their interests.

For each paper you are given, return:
- score: integer from 1 to 10 expressing relevance to the user's interest (10 = perfect match)
- summary: 2-3 sentences summarising the paper's contribution and why it is or isn't relevant

Be strict: only papers directly on-topic should score 7 or above."""

_USER_PROMPT_TEMPLATE = """User interest: {interest}

Paper title: {title}
Authors: {authors}
Published: {published_date}
Subjects: {subjects}
Abstract: {abstract}

Score and summarise this paper."""


async def _analyze_record(
    record: Record,
    interest: str,
    llm: ChatBedrockConverse,
) -> Optional[AnalyzedRecord]:
    structured_llm = llm.with_structured_output(RecordAnalysis)
    prompt = _USER_PROMPT_TEMPLATE.format(
        interest=interest,
        title=record.title,
        authors=", ".join(record.authors),
        published_date=record.published_date,
        subjects=", ".join(record.subjects),
        abstract=record.abstract,
    )
    try:
        result = cast(RecordAnalysis, await structured_llm.ainvoke([
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]))
        return AnalyzedRecord(record=record, score=result.score, summary=result.summary)
    except Exception:
        logger.exception("Failed to analyze record: %s", record.title)
        return None


async def analyze_records(
    records: list[Record],
    interest: str,
    model_id: str,
) -> list[AnalyzedRecord]:
    llm = ChatBedrockConverse(model=model_id)
    tasks = [_analyze_record(r, interest, llm) for r in records]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


# ---------------------------------------------------------------------------
# Email digest
# ---------------------------------------------------------------------------

_IACR_URL_PREFIX = "https://eprint.iacr.org/"


def _extract_iacr_paper_id(url: str) -> Optional[str]:
    if not url.startswith(_IACR_URL_PREFIX):
        return None
    return url[len(_IACR_URL_PREFIX):] or None


def _build_paper_html(ar: AnalyzedRecord, deep_dive_url: Optional[str] = None) -> str:
    authors = ", ".join(ar.record.authors) if ar.record.authors else "Unknown"
    subjects = ", ".join(ar.record.subjects) if ar.record.subjects else ""
    subjects_line = f'<p class="paper-subjects">{subjects}</p>' if subjects else ""
    deep_dive_line = (
        f'<p class="paper-deep-dive"><a href="{deep_dive_url}">Request a deep dive &rarr;</a></p>'
        if deep_dive_url else ""
    )
    return (
        f'<div class="paper">'
        f'<p class="paper-title"><a href="{ar.record.url}">{ar.record.title}</a></p>'
        f'<p class="paper-authors">{authors}</p>'
        f'<p class="paper-date">{ar.record.published_date}</p>'
        f'<span class="paper-score">Score: {ar.score}/10</span>'
        f'<p class="paper-summary">{ar.summary}</p>'
        f'{subjects_line}'
        f'{deep_dive_line}'
        f'</div>'
    )


def _make_deep_dive_url(ar: AnalyzedRecord, base_url: str, secret: str) -> Optional[str]:
    paper_id = _extract_iacr_paper_id(ar.record.url)
    if not paper_id:
        return None
    token = signing.sign(SOURCE_NAME, paper_id, secret)
    separator = "&" if "?" in base_url else "?"
    return f"{base_url.rstrip('/')}{separator}token={token}"


def _build_digest(analyzed: list[AnalyzedRecord], threshold: int) -> str:
    passing = sorted(
        [a for a in analyzed if a.score >= threshold],
        key=lambda a: a.score,
        reverse=True,
    )
    if not passing:
        return ""

    base_url = os.environ.get("DEEP_DIVE_BASE_URL")
    secret = _get_signing_secret()

    run_date = date.today().strftime("%B %-d, %Y")
    paper_count = len(passing)

    def _deep_dive_url(ar: AnalyzedRecord) -> Optional[str]:
        if base_url and secret:
            return _make_deep_dive_url(ar, base_url, secret)
        return None

    papers_html = "\n".join(_build_paper_html(a, _deep_dive_url(a)) for a in passing)
    template = TEMPLATE_PATH.read_text()
    return template.format(
        subject=f"{SOURCE_NAME} Digest — {paper_count} paper{'s' if paper_count != 1 else ''} — {run_date}",
        source_name=SOURCE_NAME,
        paper_count=paper_count,
        paper_count_plural="s" if paper_count != 1 else "",
        run_date=run_date,
        papers_html=papers_html,
        threshold=threshold,
    )


def send_digest(html: str, recipient: str, paper_count: int) -> None:
    run_date = date.today().strftime("%B %-d, %Y")
    subject = f"{SOURCE_NAME} Digest — {paper_count} paper{'s' if paper_count != 1 else ''} — {run_date}"
    ses = boto3.client("ses")
    ses.send_email(
        Source=recipient,
        Destination={"ToAddresses": [recipient]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
        },
    )
    logger.info("Digest sent to %s (%d papers)", recipient, paper_count)


# ---------------------------------------------------------------------------
# Lambda entrypoint
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context: object) -> dict:
    params = _get_ssm_params()
    interest = params[f"{SSM_PREFIX}/interest"]
    threshold = int(params[f"{SSM_PREFIX}/threshold"])
    model_id = params.get(f"{SSM_PREFIX}/bedrock-model-id", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    recipient = params["/llm-rss/recipient-email"]

    records = fetch_records()
    if not records:
        logger.info("No records fetched — nothing to do")
        return {"status": "no_records"}

    analyzed = asyncio.run(analyze_records(records, interest, model_id))
    passing = [a for a in analyzed if a.score >= threshold]

    if not passing:
        logger.info("No records cleared threshold %d — digest suppressed", threshold)
        return {"status": "below_threshold", "analyzed": len(analyzed)}

    html = _build_digest(analyzed, threshold)
    send_digest(html, recipient, len(passing))

    return {
        "status": "sent",
        "fetched": len(records),
        "analyzed": len(analyzed),
        "sent": len(passing),
    }
