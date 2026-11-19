"""
LORE Enterprise — Stage S3 LangGraph Ingestion & Settlement Tests
Tests:
1. Default Non-LLM Fast Path ($0 cost, 0 external calls).
2. Conversational Log Self-Correction Loop (pass 1 ungrounded -> critique injected -> pass 2 succeeds).
3. Max-Retry Quarantine Escalation (groundedness remains low -> routes to needs_review / S3_LOW_CONFIDENCE_QUARANTINE with node_trace).
4. Failure Fallback & Secret Scrubbing (unreachable service falls back to Multi-ML, ingestion_llm_api_key never stored).
5. LangSmith Disabled Guard (LANGCHAIN_TRACING_V2 == 'false').
6. Test Extractor LLM Endpoint (POST /api/v1/ingestion/test-extractor-llm/).
"""

import os
import json
import pytest
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.utils import timezone
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.identity.models import Organization, User
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.sources.models import SourceDocument, DocumentVersion, DocumentPage
from apps.ingestion.models import IngestionJob, IngestionPipelineRun
from apps.ingestion.settlement import (
    ExtractionValidationService,
    SettlementGateCoordinator,
    SettlementReasonCode,
)
from apps.ingestion.s3_langgraph import (
    S3ExtractionGraph,
    TransientIngestionContext,
    is_conversational_workload,
)
from apps.audit.models import AuditEvent


@pytest.fixture
def ingestion_fixture(db):
    org = Organization.objects.create(name="Cyberdyne Systems Corp", slug="cyberdyne-s3")
    user = User.objects.create_user(username="sarah_connor", email="sarah@cyberdyne.io", password="password123")
    ws = Workspace.objects.create(organization=org, name="Security & Defensive Ops", slug="security-ops")
    WorkspaceMembership.objects.create(workspace=ws, user=user, role="admin")

    raw_transcript = (
        "[10:14 AM] Alice: Hey team, we need to enforce that all external access requires hardware MFA tokens.\n"
        "[10:15 AM] Bob: Agreed. Section 5.1 of the security policy mandates FIPS 140-3 Level 2 tokens for remote VPN access.\n"
        "[10:17 AM] Alice: Effective date will be December 1st, 2026 for all personnel.\n"
        "[10:20 AM] Bob: Also, session inactivity timeouts must be locked to 15 minutes max.\n"
    )

    doc_file = SimpleUploadedFile("slack_security_audit.json", raw_transcript.encode("utf-8"), content_type="application/json")
    doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws,
        owner=user,
        title="Slack Security Audit Transcript",
        original_filename="slack_security_audit.json",
        mime_type="application/json",
        file_size=len(raw_transcript),
        file_hash="hash_slack_sec_111111111111111111111111111111111111111111111111",
        file_obj=doc_file,
        document_type="json",
        authority_level=3,
        status="queued",
    )
    ver = DocumentVersion.objects.create(
        document=doc,
        version_number=1,
        file_hash=doc.file_hash,
        file_obj=doc.file_obj,
        change_summary="Initial transcript upload",
        is_current=True,
    )

    return {
        "org": org,
        "user": user,
        "ws": ws,
        "doc": doc,
        "ver": ver,
        "transcript": raw_transcript,
    }


class TestS3LangGraphIngestion:

    def test_langsmith_tracing_disabled_guard(self):
        """Invariant 1: Assert LANGCHAIN_TRACING_V2 and LANGSMITH_TRACING are explicitly disabled."""
        assert os.environ.get("LANGCHAIN_TRACING_V2") == "false"
        assert os.environ.get("LANGSMITH_TRACING") == "false"
        assert getattr(settings, "LANGCHAIN_TRACING_V2", "") == "false"

    def test_default_non_llm_fast_path(self, ingestion_fixture):
        """
        Test 1: When ingestion_llm_enabled is False, standard files or disabled config
        bypass LLM nodes completely with mode='deterministic_multiml_fastpath' at $0 LLM cost.
        """
        doc = ingestion_fixture["doc"]
        ver = ingestion_fixture["ver"]

        config = {
            "enabled": False,
            "provider": "ollama",
            "model": "qwen2.5:14b",
        }

        # Run settlement Stage S3
        s3_res, pages = ExtractionValidationService.extract_and_validate(
            doc=doc,
            doc_version=ver,
            ingestion_config=config,
        )

        assert s3_res.status == "passed"
        assert SettlementReasonCode.S3_EXTRACTION_PASSED.value in s3_res.reason_codes
        assert "S3_LLM_EXTRACTION_PASSED" not in s3_res.reason_codes
        assert len(pages) > 0
        # Assert DocumentPages were created
        assert DocumentPage.objects.filter(document=doc).count() > 0

    def test_conversational_log_self_correction_loop(self, ingestion_fixture):
        """
        Test 2: Conversational log with ingestion_llm_enabled=True.
        Pass 1 emits an ungrounded claim (hallucinated quote -> score < 0.85).
        LangGraph loops back to extract_candidates with grader_critique.
        Pass 2 corrects the quote and succeeds with verdict='passed'.
        """
        doc = ingestion_fixture["doc"]
        ver = ingestion_fixture["ver"]

        attempt_counter = [0]

        def mock_extractor(prompt, system_prompt, config):
            attempt_counter[0] += 1
            if attempt_counter[0] == 1:
                # Pass 1: emits hallucinated quote
                return json.dumps([
                    {
                        "rule_id": "SEC-001",
                        "statement": "Hardware MFA tokens are required for all external access.",
                        "authority_hint": 4,
                        "effective_date": "2026-12-01",
                        "source_quote": "THIS TEXT DOES NOT EXIST ANYWHERE IN THE TRANSCRIPT AT ALL",
                        "page_or_timestamp": "10:14 AM"
                    }
                ])
            else:
                # Pass 2: repaired using exact verbatim quote from transcript
                return json.dumps([
                    {
                        "rule_id": "SEC-001",
                        "statement": "Hardware MFA tokens are required for external access.",
                        "authority_hint": 4,
                        "effective_date": "2026-12-01",
                        "source_quote": "all external access requires hardware MFA tokens",
                        "page_or_timestamp": "10:14 AM"
                    },
                    {
                        "rule_id": "SEC-002",
                        "statement": "Session inactivity timeouts must be locked to 15 minutes max.",
                        "authority_hint": 3,
                        "effective_date": None,
                        "source_quote": "session inactivity timeouts must be locked to 15 minutes max",
                        "page_or_timestamp": "10:20 AM"
                    }
                ])

        config = {
            "enabled": True,
            "provider": "ollama",
            "model": "qwen2.5:14b",
            "grader_model": "phi4:14b",
            "force_llm_extraction": True,
            "_mock_extractor": mock_extractor,
        }

        s3_res, pages = ExtractionValidationService.extract_and_validate(
            doc=doc,
            doc_version=ver,
            ingestion_config=config,
        )

        assert attempt_counter[0] == 2, f"Expected 2 attempts for self-repair loop, got {attempt_counter[0]}"
        assert s3_res.status == "passed"
        assert SettlementReasonCode.S3_EXTRACTION_PASSED.value in s3_res.reason_codes
        assert "S3_LLM_EXTRACTION_PASSED" in s3_res.reason_codes
        assert s3_res.details.get("mode") == "langgraph_llm_extraction"
        assert s3_res.details.get("groundedness_score") >= 0.85

        # Check telemetry trace recorded
        trace = s3_res.details.get("node_trace", [])
        node_names = [t.get("node") for t in trace]
        assert "route_intake" in node_names
        assert "extract_candidates" in node_names
        assert "cross_family_grade" in node_names
        assert "finalize_passed" in node_names

        # Check pages formatted properly
        assert len(pages) == 2
        assert pages[0]["metadata"]["verified_by_grader"] is True
        assert pages[0]["extraction_type"] == "langgraph_llm_extraction"

    def test_max_retry_quarantine_escalation(self, ingestion_fixture):
        """
        Test 3: When extraction persistently fails groundedness verification after max_retries,
        LangGraph routes document to quarantine (needs_review / S3_LOW_CONFIDENCE_QUARANTINE)
        with full node_trace attached.
        """
        doc = ingestion_fixture["doc"]
        ver = ingestion_fixture["ver"]

        def persistently_hallucinating_extractor(prompt, system_prompt, config):
            return json.dumps([
                {
                    "rule_id": "HALLUC-001",
                    "statement": "All servers must be painted neon pink by order of management.",
                    "authority_hint": 5,
                    "effective_date": "2026-01-01",
                    "source_quote": "COMPLETELY FABRICATED QUOTE NOT IN TRANSCRIPT",
                    "page_or_timestamp": "99:99"
                }
            ])

        config = {
            "enabled": True,
            "provider": "ollama",
            "model": "qwen2.5:14b",
            "grader_model": "phi4:14b",
            "force_llm_extraction": True,
            "_mock_extractor": persistently_hallucinating_extractor,
        }

        s3_res, pages = ExtractionValidationService.extract_and_validate(
            doc=doc,
            doc_version=ver,
            ingestion_config=config,
        )

        assert s3_res.status == "needs_review"
        assert SettlementReasonCode.S3_LOW_CONFIDENCE_QUARANTINE.value in s3_res.reason_codes
        assert s3_res.details.get("groundedness_score") == 0.0

        trace = s3_res.details.get("node_trace", [])
        node_names = [t.get("node") for t in trace]
        assert "route_to_quarantine" in node_names

        # Governance Quarantine Wall: document status must be quarantined/needs_review
        doc.refresh_from_db()
        assert doc.status == "needs_review"
        assert doc.governance_status == "needs_review"

    def test_ollama_failure_fallback_and_secret_scrubbing(self, ingestion_fixture):
        """
        Test 4: Unreachable Ollama server or network error gracefully falls back to Multi-ML extraction.
        Assert that ingestion_llm_api_key NEVER leaks into DB records or audit events.
        """
        doc = ingestion_fixture["doc"]
        ver = ingestion_fixture["ver"]

        secret_key_val = "sk-ingest-secret-1234567890abcdef"

        config = {
            "enabled": True,
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
            "api_key": secret_key_val,
            "force_llm_extraction": True,
            # Ollama url pointing to non-existent port to force connection failure
            "ollama_url": "http://127.0.0.1:59999",
        }

        # Simulate connection error
        def failing_extractor(prompt, system_prompt, config):
            raise ConnectionError("Failed to connect to LLM provider at http://127.0.0.1:59999")

        config["_mock_extractor"] = failing_extractor

        # Register transient context in memory
        TransientIngestionContext.set(str(doc.id), config)

        s3_res, pages = ExtractionValidationService.extract_and_validate(
            doc=doc,
            doc_version=ver,
            ingestion_config=config,
        )

        # Fallback executed cleanly
        assert s3_res.status == "passed"
        assert SettlementReasonCode.S3_EXTRACTION_PASSED.value in s3_res.reason_codes
        assert "S3_LLM_FALLBACK_TO_MULTIML" in s3_res.reason_codes
        assert len(pages) > 0

        # Invariant 5: Secret Scrubbing Verification
        doc.refresh_from_db()
        doc_dump = json.dumps(doc.validation_notes or {})
        assert secret_key_val not in doc_dump, "Secret leaked into SourceDocument.validation_notes!"

        for audit in AuditEvent.objects.filter(target_id=str(doc.id)):
            audit_dump = json.dumps(audit.details or {})
            assert secret_key_val not in audit_dump, "Secret leaked into AuditEvent.details!"

        TransientIngestionContext.clear()

    def test_test_extractor_llm_endpoint(self, ingestion_fixture, client):
        """
        Test 6: POST /api/v1/ingestion/test-extractor-llm/ validates provider connectivity.
        """
        user = ingestion_fixture["user"]
        client.force_login(user)

        # 1. Test unsupported provider
        res_bad = client.post(
            "/api/v1/ingestion/test-extractor-llm/",
            data=json.dumps({"provider": "unknown_provider"}),
            content_type="application/json"
        )
        assert res_bad.status_code == 400
        assert "Unsupported provider" in res_bad.json().get("message", "")

        # 2. Test Groq without key
        res_groq_nokey = client.post(
            "/api/v1/ingestion/test-extractor-llm/",
            data=json.dumps({"provider": "groq", "api_key": ""}),
            content_type="application/json"
        )
        assert res_groq_nokey.status_code == 400
        assert "API key is required" in res_groq_nokey.json().get("message", "")

        # 3. Test Ollama with mocked response
        mock_response_data = json.dumps({
            "models": [
                {"name": "qwen2.5:14b"},
                {"name": "phi4:14b"},
                {"name": "llama3.1:8b"}
            ]
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_data
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res_ollama = client.post(
                "/api/v1/ingestion/test-extractor-llm/",
                data=json.dumps({
                    "provider": "ollama",
                    "ollama_url": "http://localhost:11434",
                    "model": "qwen2.5:14b",
                    "grader_model": "phi4:14b"
                }),
                content_type="application/json"
            )
            assert res_ollama.status_code == 200
            data = res_ollama.json()
            assert data["status"] == "connected"
            assert data["provider"] == "ollama"
            assert "qwen2.5:14b" in data["models"]
            assert "phi4:14b" in data["models"]
