"""Deep Dive Trigger Lambda — public Function URL entry point.

Verifies the HMAC-signed token from the Deep Dive Link, returns an instant
HTTP 200 acknowledgement page, and asynchronously invokes the worker Lambda.
Rejects tampered / unsigned / malformed requests with HTTP 400.
"""

import json
import logging
import os
from pathlib import Path

import boto3
import signing

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

WORKER_FUNCTION_NAME = os.environ.get("WORKER_FUNCTION_NAME", "llm-rss-deep-dive-worker")

_ACK_TEMPLATE = Path(__file__).parent / "templates" / "ack.html"
_BAD_TEMPLATE = Path(__file__).parent / "templates" / "invalid.html"


def _html_response(status: int, body: str) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "body": body,
    }


def _bad_request(message: str) -> dict:
    body = _BAD_TEMPLATE.read_text().format(message=message)
    return _html_response(400, body)


def lambda_handler(event: dict, context: object) -> dict:
    secret = os.environ.get("DEEP_DIVE_SIGNING_SECRET")
    if not secret:
        logger.error("DEEP_DIVE_SIGNING_SECRET not configured")
        return _bad_request("Service misconfigured.")

    params = event.get("queryStringParameters") or {}
    token = params.get("token")
    if not token:
        return _bad_request("Missing token — this link appears to be incomplete.")

    signed_paper = signing.verify(token, secret)
    if signed_paper is None:
        return _bad_request("Invalid or tampered link — please request a new Deep Dive from the Digest.")

    worker = os.environ.get("WORKER_FUNCTION_NAME", WORKER_FUNCTION_NAME)
    lambda_client = boto3.client("lambda")
    lambda_client.invoke(
        FunctionName=worker,
        InvocationType="Event",
        Payload=json.dumps({"source": signed_paper.source, "paper_id": signed_paper.paper_id}),
    )
    logger.info("Async-invoked worker for %s / %s", signed_paper.source, signed_paper.paper_id)

    body = _ACK_TEMPLATE.read_text().format(
        source=signed_paper.source,
        paper_id=signed_paper.paper_id,
    )
    return _html_response(200, body)
