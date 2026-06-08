"""Behavioural tests for the Deep Dive worker handler.

External behaviour only: invoke the handler with an event, assert which email
is sent (result or failure). docling's DocumentConverter, the Bedrock LLM,
and SES are all mocked. PDF parse quality, LLM output quality, and exact
email markup are not asserted.
"""

import pytest
from unittest.mock import MagicMock, patch

import deep_dive_worker

SOURCE = "IACR ePrint"
PAPER_ID = "2024/123"


def _make_event(source=SOURCE, paper_id=PAPER_ID):
    return {"source": source, "paper_id": paper_id}


def _ssm_params():
    return {
        "/llm-rss/iacr/deep-dive-model-id": "us.anthropic.claude-sonnet-4-6",
        "/llm-rss/recipient-email": "user@example.com",
    }


def _make_analysis():
    return deep_dive_worker.DeepDiveAnalysis(
        tldr="Short summary.",
        problem_and_motivation="The problem.",
        key_contributions="Contributions.",
        how_it_works="The mechanism.",
        results_and_evidence="Results.",
        limitations_and_assumptions="Limitations.",
        title="Test Paper",
    )


# ---------------------------------------------------------------------------
# Cycle 1: Happy path → result email sent
# ---------------------------------------------------------------------------

def test_happy_path_sends_result_email(monkeypatch):
    monkeypatch.setenv("DEEP_DIVE_SIGNING_SECRET", "test-secret")

    mock_converter = MagicMock()
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = "# Test Paper\n\nFull paper text."
    mock_result = MagicMock()
    mock_result.document = mock_doc
    mock_converter.return_value.convert.return_value = mock_result

    mock_llm_instance = MagicMock()
    mock_llm_instance.with_structured_output.return_value.invoke.return_value = _make_analysis()
    mock_llm_class = MagicMock(return_value=mock_llm_instance)

    mock_ses = MagicMock()
    mock_ssm = MagicMock()
    mock_ssm.get_parameters.return_value = {
        "Parameters": [{"Name": k, "Value": v} for k, v in _ssm_params().items()]
    }

    with patch("deep_dive_worker.DocumentConverter", mock_converter), \
         patch("deep_dive_worker.PdfPipelineOptions", MagicMock()), \
         patch("deep_dive_worker.PdfFormatOption", MagicMock()), \
         patch("deep_dive_worker.InputFormat", MagicMock()), \
         patch("deep_dive_worker.ChatBedrockConverse", mock_llm_class), \
         patch("boto3.client") as mock_boto3_client:
        mock_boto3_client.side_effect = lambda svc: mock_ssm if svc == "ssm" else mock_ses
        result = deep_dive_worker.lambda_handler(_make_event(), {})

    assert result["status"] == "sent"
    mock_ses.send_email.assert_called_once()
    call_kwargs = mock_ses.send_email.call_args[1]
    assert "Deep Dive" in call_kwargs["Message"]["Subject"]["Data"]
    assert "Test Paper" in call_kwargs["Message"]["Subject"]["Data"]
    assert "failure" not in call_kwargs["Message"]["Subject"]["Data"].lower()


# ---------------------------------------------------------------------------
# Cycle 6: the analysis LLM is built with an explicit, generous max_tokens.
# Without it Bedrock applies a low default output cap and truncates mid-way
# through the long ``how_it_works`` section, so the trailing
# ``results_and_evidence``/``limitations_and_assumptions`` fields never arrive
# and structured-output validation fails with "Field required".
# ---------------------------------------------------------------------------

def test_analysis_llm_sets_generous_max_tokens(monkeypatch):
    monkeypatch.setenv("DEEP_DIVE_SIGNING_SECRET", "test-secret")

    mock_converter = MagicMock()
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = "# Test Paper\n\nFull paper text."
    mock_result = MagicMock()
    mock_result.document = mock_doc
    mock_converter.return_value.convert.return_value = mock_result

    mock_llm_instance = MagicMock()
    mock_llm_instance.with_structured_output.return_value.invoke.return_value = _make_analysis()
    mock_llm_class = MagicMock(return_value=mock_llm_instance)

    mock_ses = MagicMock()
    mock_ssm = MagicMock()
    mock_ssm.get_parameters.return_value = {
        "Parameters": [{"Name": k, "Value": v} for k, v in _ssm_params().items()]
    }

    with patch("deep_dive_worker.DocumentConverter", mock_converter), \
         patch("deep_dive_worker.PdfPipelineOptions", MagicMock()), \
         patch("deep_dive_worker.PdfFormatOption", MagicMock()), \
         patch("deep_dive_worker.InputFormat", MagicMock()), \
         patch("deep_dive_worker.ChatBedrockConverse", mock_llm_class), \
         patch("boto3.client") as mock_boto3_client:
        mock_boto3_client.side_effect = lambda svc: mock_ssm if svc == "ssm" else mock_ses
        deep_dive_worker.lambda_handler(_make_event(), {})

    llm_kwargs = mock_llm_class.call_args[1]
    assert llm_kwargs.get("max_tokens", 0) >= 8192


# ---------------------------------------------------------------------------
# Cycle 4: PDF fetch sends a browser User-Agent so Cloudflare (which fronts
# eprint.iacr.org) does not 403 the default docling-core User-Agent.
# ---------------------------------------------------------------------------

def test_pdf_fetch_passes_browser_user_agent(monkeypatch):
    monkeypatch.setenv("DEEP_DIVE_SIGNING_SECRET", "test-secret")

    mock_converter = MagicMock()
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = "# Test Paper\n\nFull paper text."
    mock_result = MagicMock()
    mock_result.document = mock_doc
    mock_converter.return_value.convert.return_value = mock_result

    mock_llm_instance = MagicMock()
    mock_llm_instance.with_structured_output.return_value.invoke.return_value = _make_analysis()
    mock_llm_class = MagicMock(return_value=mock_llm_instance)

    mock_ses = MagicMock()
    mock_ssm = MagicMock()
    mock_ssm.get_parameters.return_value = {
        "Parameters": [{"Name": k, "Value": v} for k, v in _ssm_params().items()]
    }

    with patch("deep_dive_worker.DocumentConverter", mock_converter), \
         patch("deep_dive_worker.PdfPipelineOptions", MagicMock()), \
         patch("deep_dive_worker.PdfFormatOption", MagicMock()), \
         patch("deep_dive_worker.InputFormat", MagicMock()), \
         patch("deep_dive_worker.ChatBedrockConverse", mock_llm_class), \
         patch("boto3.client") as mock_boto3_client:
        mock_boto3_client.side_effect = lambda svc: mock_ssm if svc == "ssm" else mock_ses
        deep_dive_worker.lambda_handler(_make_event(), {})

    convert_kwargs = mock_converter.return_value.convert.call_args[1]
    headers = convert_kwargs.get("headers", {})
    user_agent = headers.get("User-Agent", "")
    assert "Mozilla" in user_agent
    assert "docling" not in user_agent.lower()


# ---------------------------------------------------------------------------
# Cycle 5: docling reads prefetched models from a fixed artifacts path (not
# $HOME, which is read-only in Lambda) and skips OCR (whose cache also lives
# under $HOME). Otherwise model resolution writes to the read-only filesystem
# and parsing dies with EROFS.
# ---------------------------------------------------------------------------

def test_parse_pdf_uses_prefetched_models_and_skips_ocr(monkeypatch):
    monkeypatch.setenv("DEEP_DIVE_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("DOCLING_ARTIFACTS_PATH", "/opt/docling-models")

    mock_converter = MagicMock()
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = "# Test Paper\n\nFull paper text."
    mock_result = MagicMock()
    mock_result.document = mock_doc
    mock_converter.return_value.convert.return_value = mock_result

    mock_pipeline_options = MagicMock()
    mock_pdf_format_option = MagicMock()

    mock_llm_instance = MagicMock()
    mock_llm_instance.with_structured_output.return_value.invoke.return_value = _make_analysis()
    mock_llm_class = MagicMock(return_value=mock_llm_instance)

    mock_ses = MagicMock()
    mock_ssm = MagicMock()
    mock_ssm.get_parameters.return_value = {
        "Parameters": [{"Name": k, "Value": v} for k, v in _ssm_params().items()]
    }

    with patch("deep_dive_worker.DocumentConverter", mock_converter), \
         patch("deep_dive_worker.PdfPipelineOptions", mock_pipeline_options), \
         patch("deep_dive_worker.PdfFormatOption", mock_pdf_format_option), \
         patch("deep_dive_worker.InputFormat", MagicMock()), \
         patch("deep_dive_worker.ChatBedrockConverse", mock_llm_class), \
         patch("boto3.client") as mock_boto3_client:
        mock_boto3_client.side_effect = lambda svc: mock_ssm if svc == "ssm" else mock_ses
        result = deep_dive_worker.lambda_handler(_make_event(), {})

    assert result["status"] == "sent"
    pipeline_kwargs = mock_pipeline_options.call_args[1]
    assert pipeline_kwargs["artifacts_path"] == "/opt/docling-models"
    assert pipeline_kwargs["do_ocr"] is False


# ---------------------------------------------------------------------------
# Cycle 2: docling failure → failure email sent
# ---------------------------------------------------------------------------

def test_docling_failure_sends_failure_email(monkeypatch):
    monkeypatch.setenv("DEEP_DIVE_SIGNING_SECRET", "test-secret")

    mock_converter = MagicMock()
    mock_converter.return_value.convert.side_effect = RuntimeError("PDF corrupted")

    mock_ses = MagicMock()
    mock_ssm = MagicMock()
    mock_ssm.get_parameters.return_value = {
        "Parameters": [{"Name": k, "Value": v} for k, v in _ssm_params().items()]
    }

    with patch("deep_dive_worker.DocumentConverter", mock_converter), \
         patch("boto3.client") as mock_boto3_client:
        mock_boto3_client.side_effect = lambda svc: mock_ssm if svc == "ssm" else mock_ses
        result = deep_dive_worker.lambda_handler(_make_event(), {})

    assert result["status"] == "failure"
    mock_ses.send_email.assert_called_once()
    call_kwargs = mock_ses.send_email.call_args[1]
    subject = call_kwargs["Message"]["Subject"]["Data"]
    assert "could not analyze" in subject.lower() or "failure" in subject.lower() or "deep dive" in subject.lower()


# ---------------------------------------------------------------------------
# Cycle 3: LLM failure → failure email sent
# ---------------------------------------------------------------------------

def test_llm_failure_sends_failure_email(monkeypatch):
    monkeypatch.setenv("DEEP_DIVE_SIGNING_SECRET", "test-secret")

    mock_converter = MagicMock()
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = "# Some paper"
    mock_result = MagicMock()
    mock_result.document = mock_doc
    mock_converter.return_value.convert.return_value = mock_result

    mock_llm_instance = MagicMock()
    mock_llm_instance.with_structured_output.return_value.invoke.side_effect = RuntimeError("model overloaded")
    mock_llm_class = MagicMock(return_value=mock_llm_instance)

    mock_ses = MagicMock()
    mock_ssm = MagicMock()
    mock_ssm.get_parameters.return_value = {
        "Parameters": [{"Name": k, "Value": v} for k, v in _ssm_params().items()]
    }

    with patch("deep_dive_worker.DocumentConverter", mock_converter), \
         patch("deep_dive_worker.ChatBedrockConverse", mock_llm_class), \
         patch("boto3.client") as mock_boto3_client:
        mock_boto3_client.side_effect = lambda svc: mock_ssm if svc == "ssm" else mock_ses
        result = deep_dive_worker.lambda_handler(_make_event(), {})

    assert result["status"] == "failure"
    mock_ses.send_email.assert_called_once()
    call_kwargs = mock_ses.send_email.call_args[1]
    body_html = call_kwargs["Message"]["Body"]["Html"]["Data"]
    assert "could not analyze" in body_html.lower()
