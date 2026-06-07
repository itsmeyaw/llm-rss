"""Deep Dive worker Lambda handler.

Given a {source, paper_id} event, derives the PDF URL via the shared signing
module, parses the full PDF with docling, analyzes it with a stronger LLM,
and delivers the result as a separate SES email. On any failure a failure email
is sent instead of failing silently.
"""

import logging
from pathlib import Path

import boto3
from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel

try:
    from docling.document_converter import DocumentConverter
except ImportError:
    DocumentConverter = None  # type: ignore[assignment,misc]

import signing

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SSM_PREFIX = "/llm-rss/iacr"
TEMPLATE_PATH = Path(__file__).parent / "templates" / "deep_dive.html"

# Truncation limit to avoid exceeding model context window (~200k chars ≈ ~50k tokens)
_MAX_MARKDOWN_CHARS = 200_000


# ---------------------------------------------------------------------------
# Analysis schema
# ---------------------------------------------------------------------------

class DeepDiveAnalysis(BaseModel):
    title: str
    tldr: str
    problem_and_motivation: str
    key_contributions: str
    how_it_works: str
    results_and_evidence: str
    limitations_and_assumptions: str


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _get_ssm_params() -> dict:
    ssm = boto3.client("ssm")
    names = [
        f"{SSM_PREFIX}/deep-dive-model-id",
        "/llm-rss/recipient-email",
    ]
    response = ssm.get_parameters(Names=names, WithDecryption=True)
    return {p["Name"]: p["Value"] for p in response["Parameters"]}


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

def _parse_pdf(pdf_url: str) -> str:
    converter = DocumentConverter()
    result = converter.convert(pdf_url)
    markdown = result.document.export_to_markdown()
    if len(markdown) > _MAX_MARKDOWN_CHARS:
        logger.warning("Markdown truncated from %d to %d chars", len(markdown), _MAX_MARKDOWN_CHARS)
        markdown = markdown[:_MAX_MARKDOWN_CHARS]
    return markdown


# ---------------------------------------------------------------------------
# LLM analysis
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a research assistant producing a detailed analysis of an academic paper.

Analyze the full paper text provided and return a structured analysis with these sections:
- title: the paper's title
- tldr: 2–3 sentence summary of the paper's core idea and significance
- problem_and_motivation: what problem the paper addresses and why it matters
- key_contributions: the main contributions, listed concisely
- how_it_works: a thorough walkthrough of the actual mechanism, protocol, or construction — not a restatement of the abstract. This is the centrepiece.
- results_and_evidence: experimental results, proofs, or evidence supporting the claims
- limitations_and_assumptions: constraints, assumptions, open questions, or weaknesses the authors acknowledge or that are evident

Be precise and technical. Do not pad."""

_USER_PROMPT_TEMPLATE = """Paper text (may be truncated):

{markdown}"""


def _analyze(markdown: str, model_id: str) -> DeepDiveAnalysis:
    llm = ChatBedrockConverse(model=model_id)
    structured_llm = llm.with_structured_output(DeepDiveAnalysis)
    prompt = _USER_PROMPT_TEMPLATE.format(markdown=markdown)
    return structured_llm.invoke([
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ])


# ---------------------------------------------------------------------------
# Email delivery
# ---------------------------------------------------------------------------

def _build_result_html(analysis: DeepDiveAnalysis) -> str:
    template = TEMPLATE_PATH.read_text()
    return template.format(
        title=analysis.title,
        tldr=analysis.tldr,
        problem_and_motivation=analysis.problem_and_motivation,
        key_contributions=analysis.key_contributions,
        how_it_works=analysis.how_it_works,
        results_and_evidence=analysis.results_and_evidence,
        limitations_and_assumptions=analysis.limitations_and_assumptions,
    )


def _build_failure_html(paper_id: str, reason: str) -> str:
    return (
        f"<html><body>"
        f"<p>Could not analyze paper <strong>{paper_id}</strong>.</p>"
        f"<p>Reason: {reason}</p>"
        f"</body></html>"
    )


def _send_email(ses, recipient: str, subject: str, html: str) -> None:
    ses.send_email(
        Source=recipient,
        Destination={"ToAddresses": [recipient]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
        },
    )


# ---------------------------------------------------------------------------
# Lambda entrypoint
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context: object) -> dict:
    paper_id = event.get("paper_id", "")

    params = _get_ssm_params()
    model_id = params.get(f"{SSM_PREFIX}/deep-dive-model-id", "us.anthropic.claude-sonnet-4-6")
    recipient = params["/llm-rss/recipient-email"]

    ses = boto3.client("ses")

    pdf_url = signing.derive_pdf_url(paper_id)
    if not pdf_url:
        logger.error("Invalid paper_id: %s", paper_id)
        html = _build_failure_html(paper_id, "invalid paper ID")
        _send_email(ses, recipient, f"Deep Dive: could not analyze paper", html)
        return {"status": "failure", "reason": "invalid_paper_id"}

    try:
        markdown = _parse_pdf(pdf_url)
    except Exception as exc:
        logger.exception("PDF parse failed for %s", pdf_url)
        html = _build_failure_html(paper_id, f"PDF parse error: {exc}")
        _send_email(ses, recipient, f"Deep Dive: could not analyze paper", html)
        return {"status": "failure", "reason": "pdf_parse_error"}

    try:
        analysis = _analyze(markdown, model_id)
    except Exception as exc:
        logger.exception("LLM analysis failed for %s", paper_id)
        html = _build_failure_html(paper_id, f"LLM error: {exc}")
        _send_email(ses, recipient, f"Deep Dive: could not analyze paper", html)
        return {"status": "failure", "reason": "llm_error"}

    try:
        html = _build_result_html(analysis)
    except Exception as exc:
        logger.exception("Email build failed for %s", paper_id)
        html = _build_failure_html(paper_id, f"email build error: {exc}")
        _send_email(ses, recipient, f"Deep Dive: could not analyze paper", html)
        return {"status": "failure", "reason": "email_build_error"}

    subject = f"Deep Dive: {analysis.title}"
    _send_email(ses, recipient, subject, html)
    logger.info("Deep Dive sent for %s to %s", paper_id, recipient)
    return {"status": "sent", "paper_id": paper_id}
