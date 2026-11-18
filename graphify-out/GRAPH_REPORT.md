# Graph Report - LORE  (2026-11-19)

## Corpus Check
- 319 files · ~513,952 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 18 file(s) not represented in the graph (top: (none) 5, .ico 3, .bat 2)

## Summary
- 5210 nodes · 15406 edges · 208 communities (96 shown, 112 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 2101 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c72f592e`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- DecisionIntelligenceLayer
- pdf_visual.py
- SourceDocument
- charts.py
- EnterpriseGovernanceEngine
- typing
- .evaluate
- test_slack_and_pptx_ingestion.py
- layout.py
- retrieval/views.py
- Workspace
- forms.py
- test_visual_integration_contract.py
- VisualDocumentExtractor
- .search
- test_multi_hop_retrieval.py
- mcp_server.py
- SyncCheckpoint
- run_evaluation_release_gates.py
- tables.py
- StripeBillingAdapter
- django_db
- EvidencePresentationEngine
- EmailOAuthCallbackView
- governance/views.py
- DocumentChunk
- _StaticOrTagMockOCR
- GovernanceRequest
- test_neural_reranker_benchmark.py
- TestEmailConnector
- execute_tool
- .extract_document
- .expand
- os
- ApiClient
- identity/views.py
- test_selective_zkp_attestation.py
- Any
- _run_single_case
- email_views.py
- visual_schema.py
- VisualDocument
- PGVectorStore
- ConciseAnswerSynthesizer
- api.ts
- run_evaluation_suite
- TesseractOCRProvider
- requirements.py
- TestFinalEnterpriseAcceptance
- _StrictVisualBaseModel
- package.json
- RetrievalEvaluationHarness
- EnterpriseKnowledgeGridTestCase
- .sync
- run_evaluation_suite
- ingestion/tasks.py
- NeuralCrossEncoderReranker
- GovernanceEvaluationHarness
- .execute_settlement
- HeuristicReranker
- django_db
- page.tsx
- TestIngestionAndEvidencePreservation
- .create_conversation
- react
- retrieval/views.py
- TestLOREEnterprisePipeline
- i18n.tsx
- visual.py
- sources/views.py
- TextElement
- region_dict_to_visual_element
- TestEnterpriseP4Integrations
- DataSovereigntyRouter
- QuotaEnforcementService
- CircuitBreaker
- gmail.py
- compilerOptions
- test_deterministic_execution_modes.py
- decisions/views.py
- .normalize_channel
- OverviewView.tsx
- Any
- DecisionRecord
- process_ingestion_pipeline
- TestCeleryVisualBatchIngestion
- StructureAwareChunker
- SentenceTransformerEmbeddingAdapter
- TestZipArchiveSecurity
- lucide-react
- node_lineage_view
- generate_conversation_title
- .validate
- .test_all_twelve_models_and_mandatory_element_fields_present
- ResilientFallbackReranker
- GmailConnector
- TestChatDocumentUploadCompliance
- TestMCPStreamableHttpProtocol
- SecurityScreeningService
- backend
- GovernedRAGView.tsx
- ConversationViewSet
- lore_enterprise/urls.py
- ModelUnavailableError
- BaseVectorStore
- HierarchicalCommunityService
- TestNeuralRerankerAndBenchmark
- services
- test_benchmark_12_corpus.py
- .validate
- _FakeOCRProvider
- TestPermissionLayerL7
- .test_settlement_versioning_permissions_retrieval_and_mcp_compatibility
- ConversationService
- resilient_vector_search
- evaluation_suite_runner.py
- rest_framework
- MCPHttpHandler
- .test_09_comparative_evaluation_benchmark_metrics
- EnterpriseConnectorsView.tsx
- evidence_presentation.test.js
- Conversation
- TestMCPFetchAndCitationEnrichment
- .resolve_and_link_entity
- SettlementCompatibilityReport
- TestMCPComplianceCheckingAndGating
- TestMCPExternalSafetyAndSecretScrubbing
- context
- healthcheck
- mcp_server
- minio
- neo4j
- volumes
- GraphTraversalBudgetExceeded
- TestMCPSearchVsGovernedDecision
- TestMCPLineageTraceAndDecisionLogging
- celery_beat
- celery_worker
- postgres
- TestMCPToolDiscoveryAndManifest
- TestMCPTenantIsolationAndAuthorization
- frontend
- EmailConnectorView.tsx
- .__get__
- visual_schema.py
- SourcesConfig
- TestUploadMemorySettings

## God Nodes (most connected - your core abstractions)
1. `SourceDocument` - 231 edges
2. `Workspace` - 208 edges
3. `Organization` - 161 edges
4. `DocumentChunk` - 125 edges
5. `HybridRetrievalService` - 122 edges
6. `EnterpriseGovernanceEngine` - 106 edges
7. `TesseractOCRProvider` - 101 edges
8. `DocumentVersion` - 98 edges
9. `ApiClient` - 85 edges
10. `QdrantVectorStore` - 83 edges

## Surprising Connections (you probably didn't know these)
- `GroundedGenerationService` --uses--> `AnswerCompletenessValidator`  [INFERRED]
  backend/apps/decisions/engine.py → backend/apps/decisions/synthesizer.py
- `GroundedGenerationService` --uses--> `ConciseAnswerSynthesizer`  [INFERRED]
  backend/apps/decisions/engine.py → backend/apps/decisions/synthesizer.py
- `GroundedGenerationService` --uses--> `StructuredEvidencePackage`  [INFERRED]
  backend/apps/decisions/engine.py → backend/apps/governance/evidence_package.py
- `EnterpriseGovernanceEngine` --uses--> `GroundedGenerationService`  [INFERRED]
  backend/apps/governance/layers.py → backend/apps/decisions/engine.py
- `TestMasterSystemPromptAndStructuredInput` --uses--> `GroundedGenerationService`  [INFERRED]
  backend/tests/test_master_system_prompt_synthesis.py → backend/apps/decisions/engine.py

## Import Cycles
- None detected.

## Communities (208 total, 112 thin omitted)

### Community 6 - "DecisionIntelligenceLayer"
Cohesion: 0.06
Nodes (9): EnterpriseDecisionClassifier, AnswerStateTuple, AuthorityConflictTuple, DecisionIntelligenceLayer, DecisionIntelligenceTuple, SufficiencyEvaluationTuple, TemporalEvaluationTuple, TestDecisionIntelligenceLayerL1 (+1 more)

### Community 7 - "pdf_visual.py"
Cohesion: 0.05
Nodes (19): sanitize_sensitive_data(), _clamp_engine_str(), _close_image_quietly(), display_rect_to_normalized_box(), get_page_geometry(), _materialize_pdf_input(), PyMuPDFNativePDFExtractor, PyMuPDFPageRenderer (+11 more)

### Community 8 - "SourceDocument"
Cohesion: 0.03
Nodes (53): EndToEndEvaluationService, EndToEndEvaluationRun, Meta, EvaluationFailureRecord, EvaluationThresholdConfig, SequentialPipelineCoordinator, IngestionJob, Meta (+45 more)

### Community 9 - "charts.py"
Cohesion: 0.04
Nodes (57): _box_intersection_area(), build_chart_crop_reference(), calibrate_numeric_axis(), ChartExtractorConfig, ChartSourceMode, ChartType, _coerce_bool(), _collect_pymupdf_text_spans() (+49 more)

### Community 10 - "EnterpriseGovernanceEngine"
Cohesion: 0.06
Nodes (34): AnswerCompletenessValidator, AnswerStatus, ContractValidationError, Directive, EvidenceStatus, fail_closed_envelope(), GovernanceReasonCode, StructuredAnswerContract (+26 more)

### Community 11 - "typing"
Cohesion: 0.03
Nodes (37): CompliancePackLoader, ConflictRecord, EvidenceRequirement, ScopedException, L0GraphHealthMonitor, NLIConflictScanner, SettlementSecurityFunnel, DjangoORMGraphStore (+29 more)

### Community 12 - ".evaluate"
Cohesion: 0.02
Nodes (14): test_access_control_logging_retrieves_information_security_policy(), test_actual_conflict_between_relevant_sources_still_detected(), test_concise_answers_and_expandable_evidence_work(), test_draft_source_not_silently_represented_as_approved(), test_every_answer_claim_supported_by_cited_passage(), test_irrelevant_evidence_excluded_from_final_citations(), test_travel_expense_metadata_does_not_create_false_access_control_conflict(), TestAnsMdDefectsRegression (+6 more)

### Community 13 - "test_slack_and_pptx_ingestion.py"
Cohesion: 0.04
Nodes (23): PermissionLayer, process_document_job(), ZipImportEntry, Meta, ZipImportJob, Meta, DocumentPageSerializer, Meta (+15 more)

### Community 14 - "layout.py"
Cohesion: 0.03
Nodes (48): build_visual_region_provenance(), OCROutputContract, rect_to_normalized_box(), SourceDocumentVisualNotesContract, validate_normalized_box(), VisualPageMetadataContract, VisualProviderResultContract, VisualRegionProvenanceContract (+40 more)

### Community 15 - "retrieval/views.py"
Cohesion: 0.10
Nodes (10): RetrievalConfiguration, Meta, RetrievalOptimizationRun, Meta, EvidenceDrivenOptimizationService, make_search_fn(), test_candidate_generation_and_comparison(), test_configuration_rollback_restores_known_good() (+2 more)

### Community 16 - "Workspace"
Cohesion: 0.06
Nodes (41): AuditEvent, Meta, TelemetryService, Organization, OrganizationMembership, Meta, Command, Workspace (+33 more)

### Community 17 - "forms.py"
Cohesion: 0.05
Nodes (36): crop_box_to_page_coords(), _analyze_signature_roi(), _as_box4(), _assign_column_index(), build_form_crop_reference(), _classify_checkbox_roi(), classify_form_subtype(), _classify_radio_roi() (+28 more)

### Community 18 - "test_visual_integration_contract.py"
Cohesion: 0.03
Nodes (31): CanonicalExtractedPageContract, DocumentExtractorProtocol, OCRProviderProtocol, OCRRouterProtocol, VisualContractError, VisualContractValidationError, VisualDocumentExtractorProtocol, VisualExtensionHookProtocol (+23 more)

### Community 19 - "VisualDocumentExtractor"
Cohesion: 0.07
Nodes (13): BaseVisualProvider, crop_image_safe(), HTMLVisualProbe, LocalDeterministicVisualProvider, normalize_bbox(), OfficeVisualProbe, _open_zip_safe(), PDFVisualProbe (+5 more)

### Community 21 - "test_multi_hop_retrieval.py"
Cohesion: 0.04
Nodes (9): EvidenceItem, StructuredEvidencePackage, MultiHopResult, QueryDecomposer, SubQuery, QueryAnalysis, QueryUnderstandingService, TestMasterSystemPromptAndStructuredInput (+1 more)

### Community 22 - "mcp_server.py"
Cohesion: 0.08
Nodes (28): dispatch_jsonrpc_request(), get_organization_id(), handle_attest_compliance(), handle_bootstrap(), handle_check_compliance(), handle_check_evidence_sufficiency(), handle_detect_conflicts(), handle_escalate_to_human() (+20 more)

### Community 23 - "SyncCheckpoint"
Cohesion: 0.06
Nodes (11): BaseConnector, SyncCheckpoint, SyncEvent, ConfluenceConnector, GitHubConnector, JiraConnector, LocalFolderConnector, EnterpriseConnectorRegistry (+3 more)

### Community 24 - "run_evaluation_release_gates.py"
Cohesion: 0.07
Nodes (18): EvaluationDimensionsResult, GoldTestCase, IndependentSemanticEvaluator, LoreEvaluationEngine, PipelineStage, PipelineStageDiagnosticsEngine, SingleCaseEvaluationReport, StageDiagnostics (+10 more)

### Community 25 - "tables.py"
Cohesion: 0.03
Nodes (43): _assign_native_words_exclusively(), _box_intersection_area(), _build_grid_and_reconstructions(), CellSource, CellStatus, _coerce_bool(), _collect_adjacent_layout_footnotes(), crop_box_to_page_coords() (+35 more)

### Community 26 - "StripeBillingAdapter"
Cohesion: 0.16
Nodes (4): BaseBillingAdapter, get_billing_adapter(), LocalDevBillingAdapter, StripeBillingAdapter

### Community 27 - "django_db"
Cohesion: 0.05
Nodes (25): Migration, Migration, Migration, Migration, Migration, Migration, Migration, Migration (+17 more)

### Community 28 - "EvidencePresentationEngine"
Cohesion: 0.06
Nodes (8): EvidencePresentationEngine, TestDocumentStatusResolution, TestEvidenceDeduplication, TestEvidenceTypeClassification, TestMetadataFidelity, TestShortestExactPassage, TestSourceLimitations, TestUnnecessarySourceExclusion

### Community 30 - "governance/views.py"
Cohesion: 0.04
Nodes (42): compliance_packs_apply_view(), compliance_packs_list_view(), ConflictRecordSerializer, Meta, ConflictViewSet, EndToEndEvaluationRunSerializer, Meta, evaluation_baseline_view() (+34 more)

### Community 31 - "DocumentChunk"
Cohesion: 0.05
Nodes (12): DocumentChunk, Meta, EmbeddingConfigurationError, get_embedding_adapter(), reset_embedding_adapter(), validate_embedding_configuration(), BaseLexicalSearchBackend, LexicalSearchService (+4 more)

### Community 33 - "GovernanceRequest"
Cohesion: 0.05
Nodes (4): GovernanceRequest, TestInvariantEnforcement, TestResilienceAndDeterminism, TestStructuredEvidenceSynthesis

### Community 34 - "test_neural_reranker_benchmark.py"
Cohesion: 0.13
Nodes (8): BaseReranker, RerankerDiagnostics, RerankerException, RerankingTimeoutError, RerankResult, get_reranker(), RerankerFactory, ShadowRerankerEvaluator

### Community 36 - "execute_tool"
Cohesion: 0.11
Nodes (4): execute_tool(), TestMCPAliasEquivalence, TestMCPDomainGovernanceTools, TestMCPInputValidationAndErrors

### Community 37 - ".extract_document"
Cohesion: 0.06
Nodes (8): EmlFileExtractor, HTMLExtractor, PresentationExtractor, SpreadsheetExtractor, TextExtractor, TestMultiFormatExtensions, create_realistic_pptx(), TestPresentationExtractionAndIngestion

### Community 39 - "os"
Cohesion: 0.03
Nodes (17): Command, JudgeDistillationPair, Meta, get_graph_store(), get_vector_store(), Command, Command, Command (+9 more)

### Community 42 - "identity/views.py"
Cohesion: 0.07
Nodes (18): GuestModeAuthentication, SCIMService, OrganizationMembershipSerializer, Meta, OrganizationSerializer, Meta, UserSerializer, Meta (+10 more)

### Community 43 - "test_selective_zkp_attestation.py"
Cohesion: 0.06
Nodes (26): zk_verify_view(), build_merkle_tree(), compute_workspace_state_root(), _extract_workspace_stable_rules(), generate_merkle_inclusion_proof(), hash_leaf_preimage(), _pad_leaves_to_power_of_two(), verify_merkle_inclusion_proof() (+18 more)

### Community 45 - "_run_single_case"
Cohesion: 0.08
Nodes (6): BenchmarkEvaluator, BenchmarkExecutionRecord, BenchmarkTestCase, build_benchmark_test_cases(), _run_single_case(), TestLoreRegressionBenchmark

### Community 46 - "email_views.py"
Cohesion: 0.09
Nodes (11): EmailSyncService, EmailConnectionViewSet, models_q(), EmailAccountConnection, Meta, EmailSyncJob, Meta, EmailAccountConnectionSerializer (+3 more)

### Community 47 - "visual_schema.py"
Cohesion: 0.27
Nodes (16): ChartDataPoint, ChartType, ChartValuePrecision, CoordinateSpace, FormFieldStatus, FormFieldType, SelectionState, SourceMode (+8 more)

### Community 48 - "VisualDocument"
Cohesion: 0.11
Nodes (8): assess_visual_document_settlement_readiness(), build_settlement_visual_provenance(), extract_visual_document_screenable_text(), migrate_visual_payload(), validate_visual_document_payload(), VisualDocument, TestSchemaVersionSerializationAndEvolution, _UnavailableOCRProvider

### Community 51 - "api.ts"
Cohesion: 0.10
Nodes (28): IngestionActivityViewProps, KnowledgeGridViewProps, SimNode, BatchReviewPayload, BoundingBox, CanonicalEntitySummary, CompliancePack, DomainSummaryCommunity (+20 more)

### Community 54 - "TesseractOCRProvider"
Cohesion: 0.07
Nodes (19): CheckboxState, FormDocumentSubtype, FormFieldDataType, FormFieldStatus, FormKVExtractor, BaseOCRProvider, TesseractOCRProvider, _build_worker_adapter() (+11 more)

### Community 55 - "requirements.py"
Cohesion: 0.12
Nodes (9): _is_active_hotel_cap_query(), _is_leave_carryover_query(), _is_procurement_over_25k(), _is_travel_exception_action_request(), _is_vendor_onboarding_action(), RequirementEvaluationResult, RequirementHandlingStrategy, RequirementRegistry (+1 more)

### Community 56 - "TestFinalEnterpriseAcceptance"
Cohesion: 0.10
Nodes (3): create_test_chunk(), create_test_document(), TestFinalEnterpriseAcceptance

### Community 57 - "_StrictVisualBaseModel"
Cohesion: 0.12
Nodes (5): ChartAxis, ChartSeries, FormField, FormRadioGroup, _StrictVisualBaseModel

### Community 58 - "package.json"
Cohesion: 0.10
Nodes (26): eslintConfig, devDependencies, eslint@^9, eslint-config-next@^16.4.6, tailwindcss@^4, @tailwindcss/turbopack@^4, @types/node@^20, @types/react@^19 (+18 more)

### Community 59 - "RetrievalEvaluationHarness"
Cohesion: 0.12
Nodes (7): RetrievalEvaluationHarness, RetrievalMetricsResult, RetrievalTestCase, test_baseline_evaluation_metrics_computation(), test_policy_version_and_authority_precedence(), test_rejection_of_regressive_or_leaking_candidate(), test_tuning_vs_heldout_dataset_separation()

### Community 60 - "EnterpriseKnowledgeGridTestCase"
Cohesion: 0.05
Nodes (12): evaluate_gate(), main(), BaseSystemOfRecordConnector, JiraEvidenceConnector, LiveEvidenceRegistry, LiveEvidenceStatus, ServiceNowEvidenceConnector, VantaEvidenceConnector (+4 more)

### Community 62 - "run_evaluation_suite"
Cohesion: 0.16
Nodes (9): evaluate_governance_correctness(), evaluate_graphrag_contribution(), evaluate_groundedness_and_citations(), evaluate_operational_performance(), evaluate_release_gates(), evaluate_retrieval_quality(), evaluate_tenant_isolation_and_egress(), load_golden_dataset() (+1 more)

### Community 63 - "ingestion/tasks.py"
Cohesion: 0.07
Nodes (22): dispatch_pending_batch_jobs(), get_max_batch_files(), get_workload_concurrency_limit(), IngestionBatchService, purge_unsettled_partial_state(), sync_batch_status(), WorkloadConcurrencyGate, IngestionBatch (+14 more)

### Community 64 - "NeuralCrossEncoderReranker"
Cohesion: 0.14
Nodes (3): NeuralCrossEncoderReranker, LoreEnterpriseConfig, _prewarm_subsystems()

### Community 65 - "GovernanceEvaluationHarness"
Cohesion: 0.12
Nodes (3): BaselineComparator, GovernanceEvaluationHarness, Command

### Community 66 - ".execute_settlement"
Cohesion: 0.27
Nodes (7): _build_valid_visual_doc_dict(), _create_pdf_doc_and_version(), _make_pdf_bytes(), _sha256_hex(), TestVisualGovernanceInvariants, TestVisualSchemaSettlementFlow, TestVisualSettlementBypassPrevention

### Community 68 - "django_db"
Cohesion: 0.09
Nodes (6): TestDraftVsApprovedPolicyResolution, TestExpiredAndSupersededPolicyExclusion, TestFutureEffectiveAmendmentResolution, TestHistoricalExpensePredatingDoc002, TestSeparateGovernanceAttributes, TestUnverifiableApprovalStatus

### Community 69 - "page.tsx"
Cohesion: 0.19
Nodes (22): Home(), AuditView(), AuditViewProps, AuthModal(), CommandPalette(), DocumentDetailModal(), DocumentList(), Header() (+14 more)

### Community 72 - "react"
Cohesion: 0.15
Nodes (17): CommandPaletteProps, DocumentDetailModalProps, DocumentListProps, RealtimeOCRStudioProps, ReviewQueueViewProps, UploadFileItem, UploadModalProps, api (+9 more)

### Community 73 - "retrieval/views.py"
Cohesion: 0.18
Nodes (7): configurations_view(), governed_query_view(), optimization_runs_view(), promote_configuration_view(), rollback_configuration_view(), search_view(), test_groq_api_view()

### Community 75 - "i18n.tsx"
Cohesion: 0.12
Nodes (18): hindSiliguri, inter, metadata, RootLayout(), viewport, ThemeToggle(), ThemeToggleProps, I18nContext (+10 more)

### Community 76 - "visual.py"
Cohesion: 0.03
Nodes (62): WorkerExtractorRegistry, bangla_to_arabic_digits(), DigitalPDFExtractor, find_tesseract_binary(), ImagePreprocessor, is_visual_encoded_document(), OCRRouter, PDFPageRenderer (+54 more)

### Community 77 - "sources/views.py"
Cohesion: 0.08
Nodes (12): compute_idempotency_key(), dispatch_job_to_celery(), get_stale_job_timeout_seconds(), get_workload_queue_name(), EphemeralDocumentExtractionError, extract_ephemeral_document(), classify_ingestion_workload(), needs_visual_extraction() (+4 more)

### Community 78 - "TextElement"
Cohesion: 0.14
Nodes (6): BoundingBox, ExtractionProvenance, TextElement, VisualPage, _sample_bbox(), TestStrictValidationCoordinatesAndPageRefs

### Community 79 - "region_dict_to_visual_element"
Cohesion: 0.15
Nodes (11): _coerce_bounding_box_from_dict(), _coerce_crop_reference(), _discriminate_element_tag(), _extract_confidence_safely(), ExtractionWarning, _map_validation_status(), pages_to_visual_document(), region_dict_to_visual_element() (+3 more)

### Community 82 - "QuotaEnforcementService"
Cohesion: 0.13
Nodes (14): Plan, Subscription, UsageRecord, Meta, PlanSerializer, Meta, SubscriptionSerializer, Meta (+6 more)

### Community 86 - "compilerOptions"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+10 more)

### Community 88 - "test_deterministic_execution_modes.py"
Cohesion: 0.05
Nodes (16): AnswerStateMachine, GroundedGenerationService, acquire_remote_concurrency_slot(), ExecutionMode, get_active_execution_mode(), is_remote_model_allowed(), ModelExecutionMetric, ModelTaskPurpose (+8 more)

### Community 89 - "decisions/views.py"
Cohesion: 0.18
Nodes (4): ChatMessage, Meta, ChatMessageSerializer, Meta

### Community 91 - "OverviewView.tsx"
Cohesion: 0.14
Nodes (15): nextConfig, dependencies, lucide-react@^1.61.0, motion@^14.14.0, next@^16.4.6, react@19.3.0, react-dom@19.3.0, CountUp() (+7 more)

### Community 92 - "Any"
Cohesion: 0.04
Nodes (11): ExceptionEvaluationTuple, ExceptionLayer, ObservabilityLayer, TestAuthorityLayerL6, TestExceptionLayerL4, TestTemporalValidityLayerL5, TestAuthorityAndTemporalReasoning, TestContextRerankerSeparation (+3 more)

### Community 93 - "DecisionRecord"
Cohesion: 0.29
Nodes (5): DecisionRecord, Meta, DecisionRecordSerializer, Meta, DecisionRecordViewSet

### Community 95 - "TestCeleryVisualBatchIngestion"
Cohesion: 0.08
Nodes (16): DocxExtractor, PermanentIngestionError, process_visual_document_job(), TransientIngestionError, _build_mock_vstore(), _FastDeterministicOCR, _make_csv_bytes(), _make_docx_bytes() (+8 more)

### Community 97 - "SentenceTransformerEmbeddingAdapter"
Cohesion: 0.17
Nodes (3): BaseEmbeddingAdapter, HashProjectionEmbeddingAdapter, SentenceTransformerEmbeddingAdapter

### Community 98 - "TestZipArchiveSecurity"
Cohesion: 0.11
Nodes (3): create_in_memory_zip(), TestZipArchiveSecurity, TestZipIngestionEngineWorkflow

### Community 99 - "lucide-react"
Cohesion: 0.27
Nodes (12): AuthModalProps, HeaderProps, OrgSettingsProps, OverviewViewProps, NavGroupDef, NavItemDef, SidebarProps, WorkspaceSwitcherSheetProps (+4 more)

### Community 100 - "node_lineage_view"
Cohesion: 0.21
Nodes (4): graph_overview_view(), is_valid_uuid(), node_lineage_view(), _resolve_workspace()

### Community 103 - ".test_all_twelve_models_and_mandatory_element_fields_present"
Cohesion: 0.10
Nodes (8): ChartElement, FormElement, parse_visual_schema_version(), SourceCropReference, TableCell, TableElement, VisualElement, _mandatory_keys()

### Community 104 - "ResilientFallbackReranker"
Cohesion: 0.18
Nodes (3): FallbackPolicy, RerankerBackend, ResilientFallbackReranker

### Community 105 - "GmailConnector"
Cohesion: 0.07
Nodes (3): EmailAttachmentDTO, GmailConnector, _traverse_parts()

### Community 108 - "SecurityScreeningService"
Cohesion: 0.21
Nodes (3): SecurityScreeningService, SettlementStageResult, TestStage2SecurityScreening

### Community 109 - "backend"
Cohesion: 0.13
Nodes (15): container_name, depends_on, environment, ports, restart, volumes, postgres, qdrant (+7 more)

### Community 110 - "GovernedRAGView.tsx"
Cohesion: 0.21
Nodes (12): ConversationHistoryPanel(), ConversationHistoryPanelProps, GovernedMessageCard(), GovernedMessageCardProps, GovernedRAGView(), GovernedRAGViewProps, ChatMessage, Citation (+4 more)

### Community 111 - "ConversationViewSet"
Cohesion: 0.22
Nodes (3): ConversationDetailSerializer, Meta, ConversationViewSet

### Community 114 - "ModelUnavailableError"
Cohesion: 0.16
Nodes (3): ModelUnavailableError, rerank(), rerank()

### Community 119 - "services"
Cohesion: 0.15
Nodes (12): container_name, image, ports, restart, volumes, container_name, image, ports (+4 more)

### Community 129 - "evaluation_suite_runner.py"
Cohesion: 0.06
Nodes (14): build_authorized_document_filter(), SCIMRoleSynchronizer, AccessLevel, SourcePermission, QueryIntent, ContextReranker, BenchmarkRunner, TestBoundedGovernedGraphRAG (+6 more)

### Community 131 - "rest_framework"
Cohesion: 0.07
Nodes (13): AuditEventSerializer, Meta, AuditEventViewSet, OrganizationInvitation, OrganizationInvitationSerializer, Meta, connector_status_view(), connector_webhook_view() (+5 more)

### Community 133 - ".test_09_comparative_evaluation_benchmark_metrics"
Cohesion: 0.25
Nodes (3): compute_mrr(), compute_precision_at_k(), compute_recall_at_k()

### Community 134 - "EnterpriseConnectorsView.tsx"
Cohesion: 0.33
Nodes (9): ConfluenceLogo(), EnterpriseConnectorsView(), EnterpriseConnectorsViewProps, GitHubLogo(), JiraLogo(), LiveEvidenceLogo(), SharePointLogo(), WebScraperLogo() (+1 more)

### Community 136 - "evidence_presentation.test.js"
Cohesion: 0.25
Nodes (4): assert, renderCitationCard(), resolveDocumentStatus(), { test, describe }

### Community 137 - "Conversation"
Cohesion: 0.32
Nodes (4): Conversation, Meta, ConversationListSerializer, Meta

### Community 145 - "context"
Cohesion: 0.39
Nodes (8): build, args, context, dockerfile, build, build, build, build

### Community 146 - "healthcheck"
Cohesion: 0.57
Nodes (8): interval, retries, test, timeout, healthcheck, healthcheck, healthcheck, healthcheck

### Community 147 - "mcp_server"
Cohesion: 0.25
Nodes (8): command, container_name, depends_on, environment, ports, restart, volumes, mcp_server

### Community 148 - "minio"
Cohesion: 0.25
Nodes (8): command, container_name, environment, image, ports, restart, volumes, minio

### Community 149 - "neo4j"
Cohesion: 0.25
Nodes (8): container_name, environment, image, ports, profiles, restart, volumes, neo4j

### Community 150 - "volumes"
Cohesion: 0.25
Nodes (8): volumes, backend_media, kuzu_data, minio_data, neo4j_data, postgres_data, qdrant_data, sqlite_data

### Community 155 - "celery_beat"
Cohesion: 0.29
Nodes (7): command, container_name, depends_on, environment, restart, volumes, celery_beat

### Community 156 - "celery_worker"
Cohesion: 0.29
Nodes (7): command, container_name, depends_on, environment, restart, volumes, celery_worker

### Community 157 - "postgres"
Cohesion: 0.29
Nodes (7): container_name, environment, image, ports, restart, volumes, postgres

### Community 165 - "frontend"
Cohesion: 0.33
Nodes (6): container_name, depends_on, environment, ports, restart, frontend

### Community 166 - "EmailConnectorView.tsx"
Cohesion: 0.40
Nodes (5): EmailConnectorView(), EmailConnectorViewProps, GoogleWorkspaceLogo(), EmailAccountConnection, EmailSyncJob

### Community 173 - "visual_schema.py"
Cohesion: 0.13
Nodes (7): _render_chart_element_text(), _render_form_element_text(), _render_table_element_text(), _strict_enum_validator(), _truncate_str(), visual_document_to_canonical_pages(), VisualSchemaEvolutionError

## Knowledge Gaps
- **112 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SourceDocument` connect `SourceDocument` to `evaluation_suite_runner.py`, `.invalidate_workspace`, `charts.py`, `EnterpriseGovernanceEngine`, `typing`, `.evaluate`, `test_slack_and_pptx_ingestion.py`, `TestMCPFetchAndCitationEnrichment`, `retrieval/views.py`, `Workspace`, `test_visual_integration_contract.py`, `test_multi_hop_retrieval.py`, `mcp_server.py`, `SyncCheckpoint`, `tables.py`, `governance/views.py`, `DocumentChunk`, `GovernanceRequest`, `TestEmailConnector`, `.extract_document`, `os`, `test_selective_zkp_attestation.py`, `_run_single_case`, `email_views.py`, `VisualDocument`, `TesseractOCRProvider`, `TestFinalEnterpriseAcceptance`, `RetrievalEvaluationHarness`, `run_evaluation_suite`, `ingestion/tasks.py`, `.execute_settlement`, `HeuristicReranker`, `TestIngestionAndEvidencePreservation`, `TestLOREEnterprisePipeline`, `visual.py`, `sources/views.py`, `test_deterministic_execution_modes.py`, `Any`, `TestCeleryVisualBatchIngestion`, `TestZipArchiveSecurity`, `TestChatDocumentUploadCompliance`, `SecurityScreeningService`, `BaseVectorStore`, `TestPermissionLayerL7`, `ConversationService`?**
  _High betweenness centrality (0.115) - this node is a cross-community bridge._
- **Are the 121 inferred relationships involving `SourceDocument` (e.g. with `ConversationService` and `EndToEndEvaluationService`) actually correct?**
  _`SourceDocument` has 121 INFERRED edges - model-reasoned connections that need verification._
- **Should `RAPTOR: Travel & Expense Policy` be split into smaller, more focused modules?**
  _Cohesion score 0.12418300653594772 - nodes in this community are weakly interconnected._
- **Why does `Workspace` connect `Workspace` to `evaluation_suite_runner.py`, `rest_framework`, `SourceDocument`, `Conversation`, `EnterpriseGovernanceEngine`, `typing`, `TestMCPFetchAndCitationEnrichment`, `test_slack_and_pptx_ingestion.py`, `retrieval/views.py`, `test_visual_integration_contract.py`, `test_multi_hop_retrieval.py`, `mcp_server.py`, `run_evaluation_release_gates.py`, `tables.py`, `EmailOAuthCallbackView`, `governance/views.py`, `DocumentChunk`, `GovernanceRequest`, `TestEmailConnector`, `os`, `identity/views.py`, `test_selective_zkp_attestation.py`, `email_views.py`, `RetrievalEvaluationHarness`, `run_evaluation_suite`, `ingestion/tasks.py`, `HeuristicReranker`, `TestIngestionAndEvidencePreservation`, `.create_conversation`, `retrieval/views.py`, `TestLOREEnterprisePipeline`, `visual.py`, `sources/views.py`, `QuotaEnforcementService`, `test_deterministic_execution_modes.py`, `DecisionRecord`, `TestCeleryVisualBatchIngestion`, `ConversationViewSet`, `ConversationService`?**
  _High betweenness centrality (0.085) - this node is a cross-community bridge._
- **Are the 114 inferred relationships involving `Workspace` (e.g. with `AuditEvent` and `Conversation`) actually correct?**
  _`Workspace` has 114 INFERRED edges - model-reasoned connections that need verification._
- **Should `RAPTOR: Identity & Access Control` be split into smaller, more focused modules?**
  _Cohesion score 0.14285714285714285 - nodes in this community are weakly interconnected._
- **Why does `Organization` connect `Workspace` to `evaluation_suite_runner.py`, `rest_framework`, `SourceDocument`, `Conversation`, `EnterpriseGovernanceEngine`, `typing`, `TestMCPFetchAndCitationEnrichment`, `test_slack_and_pptx_ingestion.py`, `test_visual_integration_contract.py`, `test_multi_hop_retrieval.py`, `mcp_server.py`, `tables.py`, `StripeBillingAdapter`, `governance/views.py`, `DocumentChunk`, `GovernanceRequest`, `TestEmailConnector`, `os`, `identity/views.py`, `test_selective_zkp_attestation.py`, `email_views.py`, `ingestion/tasks.py`, `HeuristicReranker`, `TestIngestionAndEvidencePreservation`, `TestLOREEnterprisePipeline`, `visual.py`, `QuotaEnforcementService`, `test_deterministic_execution_modes.py`, `DecisionRecord`, `TestCeleryVisualBatchIngestion`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._