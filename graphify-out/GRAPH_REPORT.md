# Graph Report - LORE  (2026-11-19)

## Corpus Check
- 319 files · ~509,192 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 18 file(s) not represented in the graph (top: (none) 5, .ico 3, .bat 2)

## Summary
- 5218 nodes · 15360 edges · 203 communities (93 shown, 110 thin omitted)
- Extraction: 87% EXTRACTED · 13% INFERRED · 0% AMBIGUOUS · INFERRED: 2043 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `9d950263`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- EnterpriseDecisionClassifier
- pdf_visual.py
- SourceDocument
- charts.py
- EnterpriseGovernanceEngine
- typing
- .evaluate
- test_slack_and_pptx_ingestion.py
- layout.py
- RetrievalConfiguration
- Workspace
- forms.py
- VisualPipelineIntegrationAdapter
- visual.py
- TestQueryRetrievalEvaluationSuite
- QueryUnderstandingService
- HybridRetrievalService
- SyncCheckpoint
- run_evaluation_release_gates.py
- tables.py
- EndToEndEvaluationService
- django_db
- EvidencePresentationEngine
- StructuredEvidencePackage
- governance/views.py
- SqliteFullTextSearchBackend
- _StaticOrTagMockOCR
- GovernanceRequest
- BaseReranker
- SCIMService
- execute_tool
- .extract_document
- MultiDbGraphRagDeploymentTestCase
- ApiClient
- identity/views.py
- test_selective_zkp_attestation.py
- DjangoORMGraphStore
- _run_single_case
- email_views.py
- visual_schema.py
- VisualDocument
- PGVectorStore
- ConciseAnswerSynthesizer
- api.ts
- run_evaluation_suite
- TestEnterpriseLifecycleP2
- test_visual_cpu_optimization.py
- requirements.py
- TestFinalEnterpriseAcceptance
- .test_all_twelve_models_and_mandatory_element_fields_present
- package.json
- SequentialPipelineCoordinator
- EnterpriseKnowledgeGridTestCase
- EnterpriseConnectorRegistry
- GraphStoreInterface
- ingestion/tasks.py
- NeuralCrossEncoderReranker
- GovernanceEvaluationHarness
- .execute_settlement
- HeuristicReranker
- LiveEvidenceRegistry
- page.tsx
- TestIngestionAndEvidencePreservation
- retrieval/views.py
- react
- SourcePermission
- TestPresentationExtractionAndIngestion
- i18n.tsx
- test_visual_regression_and_security.py
- .inspect_and_validate
- TextElement
- region_dict_to_visual_element
- TestEnterpriseP4Integrations
- DataSovereigntyRouter
- QuotaEnforcementService
- CircuitBreaker
- .synthesize
- TestEvaluationAndResilienceP3
- compilerOptions
- .extract_metadata
- .synthesize_answer
- OrganizationViewSet
- .reconcile
- OverviewView.tsx
- Any
- pack_loader.py
- PresentationExtractor
- TestCeleryVisualBatchIngestion
- StructureAwareChunker
- SentenceTransformerEmbeddingAdapter
- TestZipArchiveSecurity
- lucide-react
- node_lineage_view
- TestMultiFormatExtensions
- TokenEncryptionService
- TableElement
- KuzuGraphStore
- GmailConnector
- BaselineComparator
- TestMCPStreamableHttpProtocol
- SecurityScreeningService
- backend
- GovernedRAGView.tsx
- ReviewQueueViewSet
- lore_enterprise/urls.py
- run_minimization_benchmark
- .execute_settlement
- HierarchicalCommunityService
- _HTMLTableStructureTokenizer
- services
- test_benchmark_12_corpus.py
- .detect_cycles
- _FakeOCRProvider
- MockDigitalPage
- Command
- .test_settlement_versioning_permissions_retrieval_and_mcp_compatibility
- LexicalSearchService
- abac.py
- EnterpriseKnowledgeGridTestCase
- identity/urls.py
- MCPHttpHandler
- .test_09_comparative_evaluation_benchmark_metrics
- EnterpriseConnectorsView.tsx
- .setup_corpus
- evidence_presentation.test.js
- _strict_enum_validator
- TestMCPFetchAndCitationEnrichment
- .resolve_and_link_entity
- _UnavailableOCRProvider
- context
- healthcheck
- mcp_server
- minio
- neo4j
- volumes
- GraphTraversalBudgetExceeded
- celery_beat
- celery_worker
- postgres
- TestMCPToolDiscoveryAndManifest
- frontend
- EmailConnectorView.tsx
- .__get__
- VisualSchemaEvolutionError
- TestUploadMemorySettings

## God Nodes (most connected - your core abstractions)
1. `SourceDocument` - 212 edges
2. `Workspace` - 208 edges
3. `Organization` - 161 edges
4. `DocumentChunk` - 122 edges
5. `HybridRetrievalService` - 121 edges
6. `EnterpriseGovernanceEngine` - 106 edges
7. `TesseractOCRProvider` - 101 edges
8. `DocumentVersion` - 93 edges
9. `ApiClient` - 85 edges
10. `QdrantVectorStore` - 82 edges

## Surprising Connections (you probably didn't know these)
- `IngestionBatchService` --uses--> `SequentialPipelineCoordinator`  [INFERRED]
  backend/apps/ingestion/batch.py → backend/apps/ingestion/coordinator.py
- `SequentialPipelineCoordinator` --uses--> `SettlementGateCoordinator`  [INFERRED]
  backend/apps/ingestion/coordinator.py → backend/apps/ingestion/settlement.py
- `process_ingestion_pipeline()` --uses--> `SequentialPipelineCoordinator`  [INFERRED]
  backend/apps/ingestion/tasks.py → backend/apps/ingestion/coordinator.py
- `TestCeleryVisualBatchIngestion` --uses--> `SequentialPipelineCoordinator`  [INFERRED]
  backend/tests/test_celery_visual_batch_ingestion.py → backend/apps/ingestion/coordinator.py
- `test_pipeline_run_1_to_4_strict_sequential_ordering()` --uses--> `SequentialPipelineCoordinator`  [INFERRED]
  backend/tests/test_end_to_end_final_evaluation_and_regression.py → backend/apps/ingestion/coordinator.py

## Import Cycles
- None detected.

## Communities (203 total, 110 thin omitted)

### Community 7 - "pdf_visual.py"
Cohesion: 0.05
Nodes (19): sanitize_sensitive_data(), build_visual_region_provenance(), compute_containment(), compute_iou(), bangla_to_arabic_digits(), _clamp_engine_str(), _close_image_quietly(), display_rect_to_normalized_box() (+11 more)

### Community 8 - "SourceDocument"
Cohesion: 0.04
Nodes (45): DocumentQualityService, QualityAuditReport, BoundedGraphTraversalService, DocumentChunk, Meta, EmbeddingConfigurationError, get_embedding_adapter(), validate_embedding_configuration() (+37 more)

### Community 9 - "charts.py"
Cohesion: 0.04
Nodes (61): _box_intersection_area(), build_chart_crop_reference(), calibrate_numeric_axis(), ChartExtractorConfig, ChartSourceMode, ChartType, _coerce_bool(), _collect_pymupdf_text_spans() (+53 more)

### Community 10 - "EnterpriseGovernanceEngine"
Cohesion: 0.05
Nodes (50): GroundedGenerationService, AnswerCompletenessValidator, FactRequirement, AnswerStatus, ContractValidationError, Directive, EvidenceStatus, fail_closed_envelope() (+42 more)

### Community 11 - "typing"
Cohesion: 0.04
Nodes (31): ConflictRecord, EvidenceRequirement, JudgeDistillationPair, Meta, ScopedException, L0GraphHealthMonitor, _cosine_similarity(), GraphIntegrityService (+23 more)

### Community 12 - ".evaluate"
Cohesion: 0.02
Nodes (16): test_access_control_logging_retrieves_information_security_policy(), test_actual_conflict_between_relevant_sources_still_detected(), test_concise_answers_and_expandable_evidence_work(), test_draft_source_not_silently_represented_as_approved(), test_every_answer_claim_supported_by_cited_passage(), test_irrelevant_evidence_excluded_from_final_citations(), test_travel_expense_metadata_does_not_create_false_access_control_conflict(), TestAnsMdDefectsRegression (+8 more)

### Community 13 - "test_slack_and_pptx_ingestion.py"
Cohesion: 0.03
Nodes (47): AuditEvent, Meta, compute_idempotency_key(), dispatch_job_to_celery(), get_workload_queue_name(), classify_ingestion_workload(), needs_visual_extraction(), DeduplicationService (+39 more)

### Community 14 - "layout.py"
Cohesion: 0.05
Nodes (26): ModelExecutionMetric, classify_layout_label(), _coerce_bool(), deduplicate_layout_regions(), _area(), _sort_key(), PPDocLayoutSConfig, PPDocLayoutSProvider (+18 more)

### Community 15 - "RetrievalConfiguration"
Cohesion: 0.05
Nodes (17): RetrievalEvaluationHarness, RetrievalTestCase, RetrievalConfiguration, Meta, make_search_fn(), configurations_view(), optimization_runs_view(), promote_configuration_view() (+9 more)

### Community 16 - "Workspace"
Cohesion: 0.05
Nodes (39): AccessLevel, Organization, OrganizationMembership, Meta, Command, Collection, Workspace, Meta (+31 more)

### Community 17 - "forms.py"
Cohesion: 0.04
Nodes (49): _analyze_signature_roi(), _as_box4(), _assign_column_index(), build_form_crop_reference(), CheckboxState, _classify_checkbox_roi(), classify_form_subtype(), _classify_radio_roi() (+41 more)

### Community 18 - "VisualPipelineIntegrationAdapter"
Cohesion: 0.04
Nodes (22): CanonicalExtractedPageContract, DocumentExtractorProtocol, OCROutputContract, OCRProviderProtocol, OCRRouterProtocol, rect_to_normalized_box(), SettlementCompatibilityReport, SourceDocumentVisualNotesContract (+14 more)

### Community 19 - "visual.py"
Cohesion: 0.04
Nodes (30): acquire_remote_concurrency_slot(), ExecutionMode, get_active_execution_mode(), is_remote_model_allowed(), ModelTaskPurpose, release_remote_concurrency_slot(), BaseVisualProvider, crop_image_safe() (+22 more)

### Community 21 - "QueryUnderstandingService"
Cohesion: 0.10
Nodes (4): QueryDecomposer, QueryAnalysis, QueryIntent, QueryUnderstandingService

### Community 22 - "HybridRetrievalService"
Cohesion: 0.03
Nodes (38): reset_embedding_adapter(), MultiHopResult, SubQuery, HybridRetrievalService, search_view(), dispatch_jsonrpc_request(), get_organization_id(), handle_attest_compliance() (+30 more)

### Community 23 - "SyncCheckpoint"
Cohesion: 0.04
Nodes (12): BaseConnector, SyncCheckpoint, SyncEvent, SyncResult, ConfluenceConnector, BaseEmailConnector, GitHubConnector, JiraConnector (+4 more)

### Community 24 - "run_evaluation_release_gates.py"
Cohesion: 0.07
Nodes (18): EvaluationDimensionsResult, GoldTestCase, IndependentSemanticEvaluator, LoreEvaluationEngine, PipelineStage, PipelineStageDiagnosticsEngine, SingleCaseEvaluationReport, StageDiagnostics (+10 more)

### Community 25 - "tables.py"
Cohesion: 0.03
Nodes (47): extract_form_kv_pairs(), _format_layout_region_markdown(), is_form_kv_text(), LayoutCategory, LayoutExtractorRoute, _norm_box_to_xyxy(), _normalize_raw_label(), _remap_crop_word_box() (+39 more)

### Community 26 - "EndToEndEvaluationService"
Cohesion: 0.08
Nodes (15): EndToEndEvaluationService, EndToEndEvaluationRun, Meta, EvaluationFailureRecord, test_baseline_comparison_and_improvement_demonstrated(), test_controlled_baseline_promotion_and_rollback(), test_cross_tenant_and_permission_isolation_security(), test_dual_layer_retrieval_and_answer_grounding_metrics() (+7 more)

### Community 27 - "django_db"
Cohesion: 0.04
Nodes (37): Migration, Migration, Migration, Migration, Migration, Migration, Migration, EvaluationThresholdConfig (+29 more)

### Community 28 - "EvidencePresentationEngine"
Cohesion: 0.06
Nodes (8): EvidencePresentationEngine, TestDocumentStatusResolution, TestEvidenceDeduplication, TestEvidenceTypeClassification, TestMetadataFidelity, TestShortestExactPassage, TestSourceLimitations, TestUnnecessarySourceExclusion

### Community 29 - "StructuredEvidencePackage"
Cohesion: 0.12
Nodes (3): EvidenceItem, StructuredEvidencePackage, TestMasterSystemPromptAndStructuredInput

### Community 30 - "governance/views.py"
Cohesion: 0.08
Nodes (27): compliance_packs_apply_view(), compliance_packs_list_view(), ConflictRecordSerializer, Meta, ConflictViewSet, EndToEndEvaluationRunSerializer, Meta, evaluation_baseline_view() (+19 more)

### Community 31 - "SqliteFullTextSearchBackend"
Cohesion: 0.18
Nodes (3): BaseLexicalSearchBackend, PostgresFullTextSearchBackend, SqliteFullTextSearchBackend

### Community 33 - "GovernanceRequest"
Cohesion: 0.05
Nodes (6): GovernanceRequest, AnswerQualityValidationResult, TestInvariantEnforcement, TestResilienceAndDeterminism, TestRetrievalToEvidencePipeline, TestStructuredEvidenceSynthesis

### Community 34 - "BaseReranker"
Cohesion: 0.05
Nodes (14): BaseReranker, FallbackPolicy, ModelUnavailableError, RerankerBackend, RerankerDiagnostics, RerankerException, RerankingTimeoutError, RerankResult (+6 more)

### Community 35 - "SCIMService"
Cohesion: 0.14
Nodes (3): SCIMService, scim_user_detail_view(), scim_users_view()

### Community 36 - "execute_tool"
Cohesion: 0.06
Nodes (9): execute_tool(), TestMCPAliasEquivalence, TestMCPComplianceCheckingAndGating, TestMCPDomainGovernanceTools, TestMCPExternalSafetyAndSecretScrubbing, TestMCPInputValidationAndErrors, TestMCPLineageTraceAndDecisionLogging, TestMCPSearchVsGovernedDecision (+1 more)

### Community 37 - ".extract_document"
Cohesion: 0.18
Nodes (4): DocxExtractor, HTMLExtractor, SpreadsheetExtractor, TextExtractor

### Community 42 - "identity/views.py"
Cohesion: 0.12
Nodes (12): GuestModeAuthentication, OrganizationSerializer, Meta, UserSerializer, Meta, accept_invitation_view(), login_view(), logout_view() (+4 more)

### Community 43 - "test_selective_zkp_attestation.py"
Cohesion: 0.08
Nodes (24): build_merkle_tree(), compute_workspace_state_root(), _extract_workspace_stable_rules(), generate_merkle_inclusion_proof(), hash_leaf_preimage(), _pad_leaves_to_power_of_two(), verify_merkle_inclusion_proof(), get_zk_attestation_service() (+16 more)

### Community 44 - "DjangoORMGraphStore"
Cohesion: 0.17
Nodes (4): DjangoORMGraphStore, get_graph_store(), is_edge_temporally_valid(), Neo4jGraphStore

### Community 45 - "_run_single_case"
Cohesion: 0.08
Nodes (7): BenchmarkEvaluator, BenchmarkExecutionRecord, BenchmarkRunner, BenchmarkTestCase, build_benchmark_test_cases(), _run_single_case(), TestLoreRegressionBenchmark

### Community 46 - "email_views.py"
Cohesion: 0.05
Nodes (12): EmailSyncService, EmailConnectionViewSet, models_q(), EmailAccountConnection, Meta, EmailSyncJob, Meta, EmailAccountConnectionSerializer (+4 more)

### Community 47 - "visual_schema.py"
Cohesion: 0.25
Nodes (16): ChartDataPoint, ChartType, ChartValuePrecision, CoordinateSpace, FormFieldStatus, FormFieldType, SelectionState, SourceMode (+8 more)

### Community 48 - "VisualDocument"
Cohesion: 0.10
Nodes (13): assess_visual_document_settlement_readiness(), build_settlement_visual_provenance(), _discriminate_element_tag(), extract_visual_document_screenable_text(), migrate_visual_payload(), parse_visual_schema_version(), _split_minor_extras_for_model(), _truncate_str() (+5 more)

### Community 51 - "api.ts"
Cohesion: 0.10
Nodes (28): IngestionActivityViewProps, KnowledgeGridViewProps, SimNode, BatchReviewPayload, BoundingBox, CanonicalEntitySummary, CompliancePack, DomainSummaryCommunity (+20 more)

### Community 52 - "run_evaluation_suite"
Cohesion: 0.07
Nodes (10): evaluate_governance_correctness(), evaluate_graphrag_contribution(), evaluate_groundedness_and_citations(), evaluate_operational_performance(), evaluate_release_gates(), evaluate_retrieval_quality(), evaluate_tenant_isolation_and_egress(), load_golden_dataset() (+2 more)

### Community 53 - "TestEnterpriseLifecycleP2"
Cohesion: 0.10
Nodes (4): TenantSafeCacheService, governed_query_view(), on_source_permission_changed(), TestEnterpriseLifecycleP2

### Community 54 - "test_visual_cpu_optimization.py"
Cohesion: 0.05
Nodes (37): WorkerExtractorRegistry, configure_visual_cpu_runtime(), get_configured_cpu_threads(), get_configured_max_render_pixels(), get_configured_opencv_threads(), get_configured_tesseract_omp_threads(), get_configured_visual_concurrency(), get_configured_visual_dpi() (+29 more)

### Community 55 - "requirements.py"
Cohesion: 0.12
Nodes (9): _is_active_hotel_cap_query(), _is_leave_carryover_query(), _is_procurement_over_25k(), _is_travel_exception_action_request(), _is_vendor_onboarding_action(), RequirementEvaluationResult, RequirementHandlingStrategy, RequirementRegistry (+1 more)

### Community 56 - "TestFinalEnterpriseAcceptance"
Cohesion: 0.09
Nodes (3): create_test_chunk(), create_test_document(), TestFinalEnterpriseAcceptance

### Community 57 - ".test_all_twelve_models_and_mandatory_element_fields_present"
Cohesion: 0.08
Nodes (12): ChartAxis, ChartElement, ChartSeries, FormElement, FormField, FormRadioGroup, _render_chart_element_text(), _render_form_element_text() (+4 more)

### Community 58 - "package.json"
Cohesion: 0.10
Nodes (26): eslintConfig, devDependencies, eslint@^9, eslint-config-next@^16.4.6, tailwindcss@^4, @tailwindcss/turbopack@^4, @types/node@^20, @types/react@^19 (+18 more)

### Community 60 - "EnterpriseKnowledgeGridTestCase"
Cohesion: 0.07
Nodes (9): evaluate_gate(), main(), BaseSystemOfRecordConnector, JiraEvidenceConnector, LiveEvidenceStatus, ServiceNowEvidenceConnector, VantaEvidenceConnector, SettlementSecurityFunnel (+1 more)

### Community 63 - "ingestion/tasks.py"
Cohesion: 0.06
Nodes (26): dispatch_pending_batch_jobs(), get_max_batch_files(), get_stale_job_timeout_seconds(), get_workload_concurrency_limit(), IngestionBatchService, purge_unsettled_partial_state(), sync_batch_status(), WorkloadConcurrencyGate (+18 more)

### Community 64 - "NeuralCrossEncoderReranker"
Cohesion: 0.11
Nodes (4): NeuralCrossEncoderReranker, SourcesConfig, LoreEnterpriseConfig, _prewarm_subsystems()

### Community 66 - ".execute_settlement"
Cohesion: 0.24
Nodes (7): _build_valid_visual_doc_dict(), _create_pdf_doc_and_version(), _make_pdf_bytes(), _sha256_hex(), TestVisualGovernanceInvariants, TestVisualSchemaSettlementFlow, TestVisualSettlementBypassPrevention

### Community 67 - "HeuristicReranker"
Cohesion: 0.09
Nodes (4): HeuristicReranker, MockNeuralCrossEncoderEngine, TestNeuralRerankerAndBenchmark, TestQueryPathRerankingCoverage

### Community 68 - "LiveEvidenceRegistry"
Cohesion: 0.16
Nodes (5): LiveEvidenceRegistry, periodic_connector_sync(), periodic_l0_graph_drift_check(), periodic_live_evidence_refresh(), debug_task()

### Community 69 - "page.tsx"
Cohesion: 0.19
Nodes (22): Home(), AuditView(), AuditViewProps, AuthModal(), CommandPalette(), DocumentDetailModal(), DocumentList(), Header() (+14 more)

### Community 71 - "retrieval/views.py"
Cohesion: 0.04
Nodes (21): ChatMessage, Meta, Conversation, Meta, DecisionRecord, Meta, ChatMessageSerializer, Meta (+13 more)

### Community 72 - "react"
Cohesion: 0.15
Nodes (17): CommandPaletteProps, DocumentDetailModalProps, DocumentListProps, RealtimeOCRStudioProps, ReviewQueueViewProps, UploadFileItem, UploadModalProps, api (+9 more)

### Community 73 - "SourcePermission"
Cohesion: 0.13
Nodes (3): SourcePermission, TestGraphRAGEmpiricalBenchmark, TestEvidencePermissionPreservation

### Community 75 - "i18n.tsx"
Cohesion: 0.12
Nodes (18): hindSiliguri, inter, metadata, RootLayout(), viewport, ThemeToggle(), ThemeToggleProps, I18nContext (+10 more)

### Community 76 - "test_visual_regression_and_security.py"
Cohesion: 0.03
Nodes (44): UnifiedDocumentExtractor, BaseOCRProvider, DigitalPDFExtractor, find_tesseract_binary(), ImagePreprocessor, is_visual_encoded_document(), OCRRouter, PDFPageRenderer (+36 more)

### Community 78 - "TextElement"
Cohesion: 0.14
Nodes (7): BoundingBox, _coerce_bounding_box_from_dict(), ExtractionProvenance, TextElement, VisualPage, _sample_bbox(), TestStrictValidationCoordinatesAndPageRefs

### Community 79 - "region_dict_to_visual_element"
Cohesion: 0.19
Nodes (7): _coerce_crop_reference(), _extract_confidence_safely(), ExtractionWarning, _map_validation_status(), pages_to_visual_document(), region_dict_to_visual_element(), _warnings_from_validation_dict()

### Community 82 - "QuotaEnforcementService"
Cohesion: 0.07
Nodes (20): AnswerStateMachine, Plan, Subscription, UsageRecord, Meta, PlanSerializer, Meta, SubscriptionSerializer (+12 more)

### Community 86 - "compilerOptions"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+10 more)

### Community 89 - "OrganizationViewSet"
Cohesion: 0.21
Nodes (6): OrganizationInvitation, OrganizationInvitationSerializer, Meta, OrganizationMembershipSerializer, Meta, OrganizationViewSet

### Community 91 - "OverviewView.tsx"
Cohesion: 0.14
Nodes (15): nextConfig, dependencies, lucide-react@^1.61.0, motion@^14.14.0, next@^16.4.6, react@19.3.0, react-dom@19.3.0, CountUp() (+7 more)

### Community 92 - "Any"
Cohesion: 0.03
Nodes (16): AnswerStateTuple, AuthorityConflictTuple, DecisionIntelligenceTuple, ExceptionEvaluationTuple, ObservabilityLayer, PermissionFilterTuple, SufficiencyEvaluationTuple, TemporalEvaluationTuple (+8 more)

### Community 93 - "pack_loader.py"
Cohesion: 0.23
Nodes (3): CompliancePackLoader, CanonicalEntityType, OntologyRelationshipType

### Community 95 - "TestCeleryVisualBatchIngestion"
Cohesion: 0.06
Nodes (13): _build_mock_vstore(), _FastDeterministicOCR, _make_csv_bytes(), _make_docx_bytes(), _make_pdf_bytes(), _make_png_bytes(), _make_pptx_bytes(), _make_xlsx_bytes() (+5 more)

### Community 97 - "SentenceTransformerEmbeddingAdapter"
Cohesion: 0.17
Nodes (3): BaseEmbeddingAdapter, HashProjectionEmbeddingAdapter, SentenceTransformerEmbeddingAdapter

### Community 98 - "TestZipArchiveSecurity"
Cohesion: 0.06
Nodes (4): _load_ch_file(), create_in_memory_zip(), TestZipArchiveSecurity, TestZipIngestionEngineWorkflow

### Community 99 - "lucide-react"
Cohesion: 0.27
Nodes (12): AuthModalProps, HeaderProps, OrgSettingsProps, OverviewViewProps, NavGroupDef, NavItemDef, SidebarProps, WorkspaceSwitcherSheetProps (+4 more)

### Community 100 - "node_lineage_view"
Cohesion: 0.21
Nodes (4): graph_overview_view(), is_valid_uuid(), node_lineage_view(), _resolve_workspace()

### Community 103 - "TableElement"
Cohesion: 0.22
Nodes (3): _render_table_element_text(), TableCell, TableElement

### Community 105 - "GmailConnector"
Cohesion: 0.04
Nodes (6): EmailAttachmentDTO, EmailMessageDTO, GmailConnector, _traverse_parts(), EmailOAuthAuthorizeView, EmailOAuthCallbackView

### Community 109 - "backend"
Cohesion: 0.13
Nodes (15): container_name, depends_on, environment, ports, restart, volumes, postgres, qdrant (+7 more)

### Community 110 - "GovernedRAGView.tsx"
Cohesion: 0.21
Nodes (12): ConversationHistoryPanel(), ConversationHistoryPanelProps, GovernedMessageCard(), GovernedMessageCardProps, GovernedRAGView(), GovernedRAGViewProps, ChatMessage, Citation (+4 more)

### Community 114 - "run_minimization_benchmark"
Cohesion: 0.32
Nodes (3): create_sample_retrieved_chunks(), generate_benchmark_workload(), run_minimization_benchmark()

### Community 116 - ".execute_settlement"
Cohesion: 0.13
Nodes (4): ConflictPreScanService, SettlementGateCoordinator, SettlementStageResult, StructureValidationService

### Community 119 - "services"
Cohesion: 0.15
Nodes (12): container_name, image, ports, restart, volumes, container_name, image, ports (+4 more)

### Community 128 - "LexicalSearchService"
Cohesion: 0.21
Nodes (3): LexicalSearchService, resilient_vector_search(), _execute_fallback()

### Community 130 - "EnterpriseKnowledgeGridTestCase"
Cohesion: 0.13
Nodes (3): NLIConflictScanner, DataSovereigntyViolation, EnterpriseKnowledgeGridTestCase

### Community 131 - "identity/urls.py"
Cohesion: 0.27
Nodes (3): AuditEventSerializer, Meta, AuditEventViewSet

### Community 133 - ".test_09_comparative_evaluation_benchmark_metrics"
Cohesion: 0.25
Nodes (3): compute_mrr(), compute_precision_at_k(), compute_recall_at_k()

### Community 134 - "EnterpriseConnectorsView.tsx"
Cohesion: 0.33
Nodes (9): ConfluenceLogo(), EnterpriseConnectorsView(), EnterpriseConnectorsViewProps, GitHubLogo(), JiraLogo(), LiveEvidenceLogo(), SharePointLogo(), WebScraperLogo() (+1 more)

### Community 136 - "evidence_presentation.test.js"
Cohesion: 0.25
Nodes (4): assert, renderCitationCard(), resolveDocumentStatus(), { test, describe }

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

## Knowledge Gaps
- **110 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SourceDocument` connect `SourceDocument` to `EnterpriseKnowledgeGridTestCase`, `charts.py`, `EnterpriseGovernanceEngine`, `typing`, `.evaluate`, `test_slack_and_pptx_ingestion.py`, `TestMCPFetchAndCitationEnrichment`, `RetrievalConfiguration`, `Workspace`, `forms.py`, `visual.py`, `TestQueryRetrievalEvaluationSuite`, `HybridRetrievalService`, `SyncCheckpoint`, `tables.py`, `EndToEndEvaluationService`, `django_db`, `governance/views.py`, `GovernanceRequest`, `MultiDbGraphRagDeploymentTestCase`, `test_selective_zkp_attestation.py`, `_run_single_case`, `email_views.py`, `run_evaluation_suite`, `TestEnterpriseLifecycleP2`, `TestFinalEnterpriseAcceptance`, `EnterpriseConnectorRegistry`, `ingestion/tasks.py`, `.execute_settlement`, `HeuristicReranker`, `TestIngestionAndEvidencePreservation`, `retrieval/views.py`, `SourcePermission`, `TestPresentationExtractionAndIngestion`, `test_visual_regression_and_security.py`, `.inspect_and_validate`, `QuotaEnforcementService`, `TestEvaluationAndResilienceP3`, `Any`, `TestCeleryVisualBatchIngestion`, `TestZipArchiveSecurity`, `ReviewQueueViewSet`, `.execute_settlement`?**
  _High betweenness centrality (0.080) - this node is a cross-community bridge._
- **Are the 114 inferred relationships involving `SourceDocument` (e.g. with `ConversationService` and `EndToEndEvaluationService`) actually correct?**
  _`SourceDocument` has 114 INFERRED edges - model-reasoned connections that need verification._
- **Should `RAPTOR: Travel & Expense Policy` be split into smaller, more focused modules?**
  _Cohesion score 0.12418300653594772 - nodes in this community are weakly interconnected._
- **Why does `Workspace` connect `Workspace` to `EnterpriseKnowledgeGridTestCase`, `SourceDocument`, `EnterpriseGovernanceEngine`, `typing`, `.evaluate`, `test_slack_and_pptx_ingestion.py`, `TestMCPFetchAndCitationEnrichment`, `RetrievalConfiguration`, `forms.py`, `TestQueryRetrievalEvaluationSuite`, `HybridRetrievalService`, `run_evaluation_release_gates.py`, `EndToEndEvaluationService`, `django_db`, `governance/views.py`, `GovernanceRequest`, `SCIMService`, `MultiDbGraphRagDeploymentTestCase`, `test_selective_zkp_attestation.py`, `_run_single_case`, `email_views.py`, `run_evaluation_suite`, `TestEnterpriseLifecycleP2`, `ingestion/tasks.py`, `HeuristicReranker`, `TestIngestionAndEvidencePreservation`, `retrieval/views.py`, `SourcePermission`, `test_visual_regression_and_security.py`, `QuotaEnforcementService`, `TestEvaluationAndResilienceP3`, `GmailConnector`, `Command`?**
  _High betweenness centrality (0.079) - this node is a cross-community bridge._
- **Are the 114 inferred relationships involving `Workspace` (e.g. with `AuditEvent` and `Conversation`) actually correct?**
  _`Workspace` has 114 INFERRED edges - model-reasoned connections that need verification._
- **Should `RAPTOR: Identity & Access Control` be split into smaller, more focused modules?**
  _Cohesion score 0.14285714285714285 - nodes in this community are weakly interconnected._
- **Why does `Organization` connect `Workspace` to `EnterpriseKnowledgeGridTestCase`, `SourceDocument`, `EnterpriseGovernanceEngine`, `typing`, `.evaluate`, `test_slack_and_pptx_ingestion.py`, `TestMCPFetchAndCitationEnrichment`, `forms.py`, `TestQueryRetrievalEvaluationSuite`, `HybridRetrievalService`, `django_db`, `GovernanceRequest`, `SCIMService`, `MultiDbGraphRagDeploymentTestCase`, `identity/views.py`, `test_selective_zkp_attestation.py`, `_run_single_case`, `email_views.py`, `TestEnterpriseLifecycleP2`, `ingestion/tasks.py`, `HeuristicReranker`, `TestIngestionAndEvidencePreservation`, `retrieval/views.py`, `SourcePermission`, `test_visual_regression_and_security.py`, `QuotaEnforcementService`, `TestEvaluationAndResilienceP3`, `OrganizationViewSet`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._