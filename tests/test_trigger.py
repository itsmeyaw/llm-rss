"""Behavioural tests for the Deep Dive Trigger Lambda.

Tests cover the public lambda_handler interface. boto3 Lambda client is mocked
so no AWS credentials are required.
"""

import json
import unittest.mock as mock

import pytest

import signing
import trigger_handler as handler

SECRET = "test-signing-secret"
SOURCE = "IACR ePrint"
PAPER_ID = "2024/123"


def _make_event(token: str | None = None) -> dict:
    """Simulate a Lambda Function URL GET event."""
    params = {"token": token} if token is not None else {}
    return {
        "requestContext": {"http": {"method": "GET"}},
        "queryStringParameters": params,
    }


def _valid_token() -> str:
    return signing.sign(SOURCE, PAPER_ID, SECRET)


# ---------------------------------------------------------------------------
# Test 1: valid token → HTTP 200 with styled HTML acknowledgement
# ---------------------------------------------------------------------------

def test_valid_token_returns_200_with_html_ack(monkeypatch):
    monkeypatch.setenv("DEEP_DIVE_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WORKER_FUNCTION_NAME", "test-worker")

    with mock.patch("trigger_handler.boto3") as mock_boto3:
        mock_lambda = mock.MagicMock()
        mock_boto3.client.return_value = mock_lambda
        mock_lambda.invoke.return_value = {}

        response = handler.lambda_handler(_make_event(_valid_token()), None)

    assert response["statusCode"] == 200
    assert "text/html" in response["headers"]["Content-Type"]
    body = response["body"]
    assert "deep dive" in body.lower() or "request" in body.lower()


# ---------------------------------------------------------------------------
# Test 2: valid token → worker invoked exactly once with correct payload
# ---------------------------------------------------------------------------

def test_valid_token_invokes_worker_exactly_once_with_correct_payload(monkeypatch):
    monkeypatch.setenv("DEEP_DIVE_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WORKER_FUNCTION_NAME", "test-worker")

    with mock.patch("trigger_handler.boto3") as mock_boto3:
        mock_lambda = mock.MagicMock()
        mock_boto3.client.return_value = mock_lambda
        mock_lambda.invoke.return_value = {}

        handler.lambda_handler(_make_event(_valid_token()), None)

    mock_boto3.client.assert_called_once_with("lambda")
    mock_lambda.invoke.assert_called_once()
    call_kwargs = mock_lambda.invoke.call_args[1]
    assert call_kwargs["FunctionName"] == "test-worker"
    assert call_kwargs["InvocationType"] == "Event"
    payload = json.loads(call_kwargs["Payload"])
    assert payload == {"source": SOURCE, "paper_id": PAPER_ID}


# ---------------------------------------------------------------------------
# Test 3: tampered token → HTTP 400 + no worker invoke
# ---------------------------------------------------------------------------

def test_tampered_token_returns_400_and_does_not_invoke_worker(monkeypatch):
    monkeypatch.setenv("DEEP_DIVE_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WORKER_FUNCTION_NAME", "test-worker")

    token = _valid_token()
    payload_b64, _, mac_b64 = token.partition(".")
    forged_payload = payload_b64[:-1] + ("A" if payload_b64[-1] != "A" else "B")
    tampered = f"{forged_payload}.{mac_b64}"

    with mock.patch("trigger_handler.boto3") as mock_boto3:
        mock_lambda = mock.MagicMock()
        mock_boto3.client.return_value = mock_lambda

        response = handler.lambda_handler(_make_event(tampered), None)

    assert response["statusCode"] == 400
    assert "invalid" in response["body"].lower() or "tampered" in response["body"].lower()
    mock_lambda.invoke.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4: malformed request (no token) → HTTP 400 + no invoke
# ---------------------------------------------------------------------------

def test_missing_token_returns_400_and_does_not_invoke_worker(monkeypatch):
    monkeypatch.setenv("DEEP_DIVE_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WORKER_FUNCTION_NAME", "test-worker")

    with mock.patch("trigger_handler.boto3") as mock_boto3:
        mock_lambda = mock.MagicMock()
        mock_boto3.client.return_value = mock_lambda

        response = handler.lambda_handler(_make_event(token=None), None)

    assert response["statusCode"] == 400
    mock_lambda.invoke.assert_not_called()
