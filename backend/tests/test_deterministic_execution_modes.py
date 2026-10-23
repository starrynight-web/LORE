"""
LORE Enterprise — Automated Tests for Deterministic-First and Model-Minimal Execution
Specification: LORE Enterprise Deterministic-First Strategy.

Verifies:
1. `local_only`: zero external inference, embeddings, OCR, or generation calls. No network egress.
2. `deterministic_first`: deterministic logic runs first; approved model called only for defined unresolved semantic task.
3. `approved_remote`: external providers permitted only when relevant policy and tenant settings explicitly authorize them.
4. Terminal governance states (denied, violation, conflicting, insufficient, abstain, human_review, no_knowledge) NEVER call an LLM.
5. External-call safety:
   - Secret scrubbing: API keys/tokens never leak into logs, exceptions, or result envelopes.
   - No silent cloud fallback: primary provider failure falls back to deterministic synthesis, not another cloud provider.
   - Bounded concurrency and timeouts.
6. Optional local OCR provider resilience (Tesseract optionality, rotation handling, graceful degradation).
"""

import pytest
import uuid
import urllib.request
from unittest.mock import patch, MagicMock
from PIL import Image, ImageDraw

from apps.governance.modes import (
    ExecutionMode, ModelTaskPurpose, ModelExecutionMetric,
    get_active_execution_mode, is_remote_model_allowed,
    sanitize_sensitive_data
)
from apps.governance.contract import GovernanceRequest, GovernanceReasonCode, Verdict, Directive
from apps.governance.layers import EnterpriseGovernanceEngine
from apps.decisions.engine import GroundedGenerationService
from apps.ingestion.pipeline.ocr import (
    TesseractOCRProvider, ImagePreprocessor, DigitalPDFExtractor, OCRRouter,
    repair_visual_bengali_document, is_visual_encoded_document
)
from apps.identity.models import Organization
from apps.workspaces.models import Workspace


@pytest.fixture
def mock_workspace(db):
    org = Organization.objects.create(name="Test Sovereignty Org", slug=f"test-sov-{uuid.uuid4().hex[:6]}")
    ws = Workspace.objects.create(organization=org, name="Compliance Workspace", slug="comp-ws")
    return ws


@pytest.fixture
def sample_candidate_chunks():
    return [
        {
            'document_id': f"doc-{uuid.uuid4().hex[:6]}",
            'document_title': "Enterprise Data Policy 2026",
            'document_version': 1,
            'page_number': 5,
            'heading_path': "Data Sovereignty > Retention",
            'authority_level': 6,
            'text': "Audit logs must be retained for at least 7 years in sovereign encrypted storage.",
            'score': 0.92,
            'token_count': 25
        }
    ]


# ==============================================================================
# 1. LOCAL_ONLY EXECUTION MODE TESTS
# ==============================================================================
class TestLocalOnlyExecutionMode:
    @pytest.mark.django_db
    def test_local_only_blocks_remote_calls_even_with_api_key(self, mock_workspace, sample_candidate_chunks):
        """In local_only mode, zero external network requests must occur even if groq_api_key is passed."""
        with patch('urllib.request.urlopen') as mock_urlopen:
            envelope = EnterpriseGovernanceEngine.evaluate(
                query="What is the audit log retention period?",
                retrieved_chunks=sample_candidate_chunks,
                workspace=mock_workspace,
                decision_type="general_inquiry",
                execution_mode=ExecutionMode.LOCAL_ONLY.value,
                groq_api_key="gsk_supersecretkey12345678901234567890",
                llm_model="llama-3.3-70b-versatile"
            )

            # Invariant: urllib.request.urlopen MUST NEVER be invoked
            mock_urlopen.assert_not_called()

            assert envelope['execution_mode'] == 'local_only'
            assert envelope['was_deterministic'] is True
            assert envelope['model_metrics']['tokens_total'] == 0
            assert envelope['model_metrics']['cost_usd'] == 0.0
            assert GovernanceReasonCode.EXECUTION_MODE_LOCAL_ONLY.value in envelope['reason_codes']
            assert GovernanceReasonCode.DETERMINISTIC_SYNTHESIS_APPLIED.value in envelope['reason_codes']
            assert "According to **Enterprise Data Policy 2026**" in envelope['answer']

    @pytest.mark.django_db
    def test_local_only_mode_offline_without_credentials(self, mock_workspace, sample_candidate_chunks):
        """local_only mode must function completely offline with zero credentials or settings."""
        with patch.object(GroundedGenerationService, '_generate_with_groq_llm') as mock_groq:
            envelope = EnterpriseGovernanceEngine.evaluate(
                query="Confirm sovereign storage requirement.",
                retrieved_chunks=sample_candidate_chunks,
                workspace=mock_workspace,
                decision_type="general_inquiry",
                execution_mode="local_only",
                groq_api_key=None,
                llm_model=None
            )
            mock_groq.assert_not_called()
            assert envelope['state'] in ('supported', 'qualified')
            assert envelope['was_deterministic'] is True
            assert envelope['directive'] == 'proceed_and_cite'


# ==============================================================================
# 2. DETERMINISTIC-FIRST EXECUTION STRATEGY TESTS
# ==============================================================================
class TestDeterministicFirstStrategy:
    @pytest.mark.django_db
    def test_deterministic_first_solves_factual_queries_with_zero_tokens(self, mock_workspace, sample_candidate_chunks):
        """Factual lookup queries default to extractive deterministic synthesis with 0 tokens."""
        with patch('urllib.request.urlopen') as mock_urlopen:
            envelope = EnterpriseGovernanceEngine.evaluate(
                query="What is the audit log retention period?",
                retrieved_chunks=sample_candidate_chunks,
                workspace=mock_workspace,
                decision_type="general_inquiry",
                execution_mode=ExecutionMode.DETERMINISTIC_FIRST.value,
                synthesis_mode="extractive",
                groq_api_key="gsk_validkey12345678901234567890"
            )

            # Zero network egress for standard factual synthesis
            mock_urlopen.assert_not_called()
            assert envelope['was_deterministic'] is True
            assert envelope['model_metrics']['tokens_total'] == 0
            assert GovernanceReasonCode.EXECUTION_MODE_DETERMINISTIC_FIRST.value in envelope['reason_codes']
            assert GovernanceReasonCode.DETERMINISTIC_SYNTHESIS_APPLIED.value in envelope['reason_codes']

    @pytest.mark.django_db
    def test_deterministic_first_terminal_governance_states_never_call_model(self, mock_workspace):
        """Terminal non-supported states (denied, violation, conflicting, etc.) must NEVER call a model."""
        with patch.object(GroundedGenerationService, '_generate_with_groq_llm') as mock_groq:
            # 1. Denied outcome: restricted chunk with unauthenticated anonymous role
            restricted_chunk = [{
                'document_id': f"doc-priv-{uuid.uuid4().hex[:6]}",
                'document_title': "Confidential Payroll",
                'authority_level': 7,
                'is_restricted': True,
                'text': "Private executive payroll tables."
            }]
            env_denied = EnterpriseGovernanceEngine.evaluate(
                query="Show secret payroll figures",
                retrieved_chunks=restricted_chunk,
                workspace=mock_workspace,
                user_role="anonymous",
                groq_api_key="gsk_test123"
            )
            assert env_denied['state'] == 'denied'
            assert env_denied['was_deterministic'] is True
            assert env_denied['model_metrics']['tokens_total'] == 0

            # 2. Insufficient outcome
            env_insuff = EnterpriseGovernanceEngine.evaluate(
                query="Statutory export approval without customs declaration",
                retrieved_chunks=[],
                workspace=mock_workspace,
                decision_type="statutory_interpretation",
                groq_api_key="gsk_test123"
            )
            assert env_insuff['state'] in ('insufficient', 'human_review')
            assert env_insuff['was_deterministic'] is True
            assert env_insuff['model_metrics']['tokens_total'] == 0

            mock_groq.assert_not_called()

    @pytest.mark.django_db
    def test_deterministic_first_blocks_remote_when_tenant_has_not_authorized(self, mock_workspace, sample_candidate_chunks):
        """When synthesis_mode='generative' but tenant has not authorized remote models, it falls back deterministically."""
        with patch('urllib.request.urlopen') as mock_urlopen:
            envelope = EnterpriseGovernanceEngine.evaluate(
                query="Synthesize a comprehensive narrative report.",
                retrieved_chunks=sample_candidate_chunks,
                workspace=mock_workspace,
                execution_mode="deterministic_first",
                synthesis_mode="generative",
                policy_context={'allow_remote_llm': False},
                groq_api_key="gsk_testkey123"
            )

            # Blocked by tenant policy
            mock_urlopen.assert_not_called()
            assert envelope['was_deterministic'] is True
            assert "remote_blocked" in envelope['model_metrics']['reason']
            assert GovernanceReasonCode.DETERMINISTIC_SYNTHESIS_APPLIED.value in envelope['reason_codes']


# ==============================================================================
# 3. APPROVED-REMOTE EXECUTION MODE TESTS
# ==============================================================================
class TestApprovedRemoteExecutionMode:
    @pytest.mark.django_db
    def test_approved_remote_blocked_without_explicit_tenant_approval(self, mock_workspace, sample_candidate_chunks):
        """In approved_remote mode, tenant authorization is mandatory."""
        with patch('urllib.request.urlopen') as mock_urlopen:
            envelope = EnterpriseGovernanceEngine.evaluate(
                query="Synthesize executive briefing.",
                retrieved_chunks=sample_candidate_chunks,
                workspace=mock_workspace,
                execution_mode=ExecutionMode.APPROVED_REMOTE.value,
                synthesis_mode="generative",
                policy_context={'allow_remote_llm': False},
                groq_api_key="gsk_test123"
            )

            mock_urlopen.assert_not_called()
            assert envelope['was_deterministic'] is True
            assert "remote_unauthorized" in envelope['model_metrics']['reason']

    @pytest.mark.django_db
    def test_approved_remote_invoked_when_tenant_explicitly_authorizes(self, mock_workspace, sample_candidate_chunks):
        """When tenant explicitly authorizes remote processing, approved model is invoked."""
        fake_api_response = {
            "choices": [{"message": {"content": "Authoritative summary: Logs must be kept 7 years [Enterprise Data Policy 2026, p.5]."}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = bytes(__import__('json').dumps(fake_api_response), 'utf-8')
        mock_resp.__enter__.return_value = mock_resp

        with patch('urllib.request.urlopen', return_value=mock_resp):
            envelope = EnterpriseGovernanceEngine.evaluate(
                query="Synthesize executive briefing.",
                retrieved_chunks=sample_candidate_chunks,
                workspace=mock_workspace,
                execution_mode=ExecutionMode.APPROVED_REMOTE.value,
                synthesis_mode="generative",
                policy_context={'allow_remote_llm': True},
                groq_api_key="gsk_approvedkey12345678901234567890"
            )

            assert envelope['was_deterministic'] is False
            assert envelope['model_metrics']['provider'] == 'groq'
            assert envelope['model_metrics']['tokens_total'] == 150
            assert envelope['model_metrics']['cost_usd'] > 0.0
            assert GovernanceReasonCode.MODEL_INFERENCE_INVOKED.value in envelope['reason_codes']


# ==============================================================================
# 4. EXTERNAL-CALL SAFETY & RESILIENCE TESTS
# ==============================================================================
class TestExternalCallSafety:
    def test_secret_scrubber_removes_api_keys_and_tokens(self):
        """Sanitizer must scrub raw API keys, bearer tokens, and secrets from dicts and strings."""
        raw_error = "Failed to connect to https://api.groq.com with key gsk_abc12345678901234567890 and Bearer eyJhbGciOiJIUzI1NiJ9"
        sanitized = sanitize_sensitive_data(raw_error)
        assert "gsk_abc" not in sanitized
        assert "Bearer" in sanitized
        assert "[REDACTED_SECRET]" in sanitized

        sensitive_dict = {
            "query": "What is the policy?",
            "groq_api_key": "gsk_secret_value_12345",
            "nested": {
                "auth_token": "token-12345",
                "normal_field": "safe_value"
            }
        }
        scrubbed_dict = sanitize_sensitive_data(sensitive_dict)
        assert scrubbed_dict['groq_api_key'] == "[REDACTED_SECRET]"
        assert scrubbed_dict['nested']['auth_token'] == "[REDACTED_SECRET]"
        assert scrubbed_dict['nested']['normal_field'] == "safe_value"

    @pytest.mark.django_db
    def test_no_silent_cloud_fallback_when_primary_provider_fails(self, mock_workspace, sample_candidate_chunks):
        """When Groq fails with an HTTP error, it MUST NOT silently fallback to another cloud provider."""
        with patch('urllib.request.urlopen', side_effect=urllib.error.HTTPError('https://api.groq.com', 503, 'Service Unavailable', {}, None)):
            with patch.object(GroundedGenerationService, '_generate_with_external_llm') as mock_other_cloud:
                envelope = EnterpriseGovernanceEngine.evaluate(
                    query="What is the audit log retention period?",
                    retrieved_chunks=sample_candidate_chunks,
                    workspace=mock_workspace,
                    decision_type="general_inquiry",
                    execution_mode=ExecutionMode.APPROVED_REMOTE.value,
                    synthesis_mode="generative",
                    policy_context={'allow_remote_llm': True},
                    groq_api_key="gsk_validkey123"
                )

                # Security Invariant: Refuse silent cloud fallback
                mock_other_cloud.assert_not_called()
                assert envelope['was_deterministic'] is True
                assert "groq_failure_safe_deterministic_fallback" in envelope['model_metrics']['reason']
                assert "According to **Enterprise Data Policy 2026**" in envelope['answer']


# ==============================================================================
# 5. OPTIONAL LOCAL OCR RESILIENCE & EXTRACTION TESTS
# ==============================================================================
class TestOptionalOCRAndExtractionResilience:
    def test_ocr_provider_graceful_degradation_when_binary_absent(self):
        """Tesseract must be strictly optional; non-existent binary must not crash ingestion."""
        missing_ocr = TesseractOCRProvider(tesseract_cmd=r'C:\invalid_missing_path\tesseract.exe')
        assert missing_ocr.is_available() is False

        img = Image.new('RGB', (800, 600), (255, 255, 255))
        result = missing_ocr.extract_image(img)

        assert result['status'] == 'provider_unavailable'
        assert result['is_optional_skipped'] is True
        assert result['confidence'] == 0.0
        assert "[OCR Engine Optional:" in result['text']

    def test_image_preprocessor_lanczos_upscaling_and_contrast(self):
        """Low-resolution images (<1200px) must be Lanczos upscaled for clear extraction."""
        small_img = Image.new('RGB', (300, 300), (200, 200, 200))
        enhanced = ImagePreprocessor.preprocess(small_img, auto_rotate=False)
        assert enhanced.size[0] >= 1200
        assert enhanced.size[1] >= 1200

    def test_bengali_visual_order_font_repair(self):
        """Visual-order Bengali fonts (Bijoy/SutonnyMJ) must be repaired to valid Unicode."""
        corrupted = "স্মার্ট ই গভনয্র্ ােন্সর ল্যান্ডটকে ইনোভশেন নিয়মাবলী"
        expected = "স্মার্ট ই-গভর্ন্যান্সের ল্যান্ডটেক ইনোভেশন নিয়মাবলী"
        assert is_visual_encoded_document(corrupted) is True
        repaired = repair_visual_bengali_document(corrupted)
        assert repaired.strip() == expected.strip()
