const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

export interface User {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  description: string;
  role: string;
}

export interface Workspace {
  id: string;
  organization: string;
  organization_name: string;
  name: string;
  slug: string;
  description: string;
  is_default: boolean;
  role: string;
}

export interface Collection {
  id: string;
  workspace: string;
  name: string;
  description: string;
  color: string;
  icon: string;
  document_count: number;
}

export interface BoundingBox {
  word: string;
  confidence: number;
  x: number;
  y: number;
  w: number;
  h: number;
  normalized_box: [number, number, number, number]; // [ymin, xmin, ymax, xmax] 0-1000
}

export interface DocumentPage {
  id: string;
  page_number: number;
  text: string;
  confidence: number;
  words_count: number;
  width: number;
  height: number;
  extraction_type: string;
  engine: string;
  engine_version: string;
  is_repaired: boolean;
  bounding_boxes: BoundingBox[];
}

export interface SourceDocument {
  id: string;
  organization: string;
  workspace: string;
  workspace_name: string;
  collection: string | null;
  collection_name: string | null;
  owner_username: string;
  title: string;
  description: string;
  original_filename: string;
  mime_type: string;
  file_size: number;
  file_hash: string;
  file_obj: string;
  document_type: string;
  status: string;
  authority_level: number;
  ocr_confidence: number;
  page_count: number;
  pages?: DocumentPage[];
  created_at: string;
  updated_at: string;
}

export interface PipelineRun {
  id: string;
  stage: 'run_1_ingestion' | 'run_2_quality' | 'run_3_retrieval' | 'run_4_decision' | string;
  status: 'pending' | 'running' | 'passed' | 'failed' | 'skipped' | 'blocked' | 'needs_review' | string;
  attempt_count: number;
  started_at: string | null;
  completed_at: string | null;
  diagnostics: Record<string, any>;
  error_message: string;
  created_at: string;
  updated_at: string;
}

export interface RetrievalConfiguration {
  id: string;
  name: string;
  version: number;
  description: string;
  is_active: boolean;
  limit: number;
  rrf_k: number;
  min_relevance_threshold: number;
  context_budget_tokens: number;
  enable_graph_expansion: boolean;
  graph_max_depth: number;
  graph_max_nodes: number;
  created_at: string;
  updated_at: string;
}

export interface RetrievalMetrics {
  total_cases: number;
  passed_cases: number;
  precision_k: number;
  recall_k: number;
  mrr: number;
  ndcg_k: number;
  correct_source_rate: number;
  evidence_coverage: number;
  citation_source_accuracy: number;
  avg_latency_ms: number;
  leakage_rate: number;
  failure_rate: number;
  category_breakdown?: Record<string, any>;
}

export interface RetrievalOptimizationRun {
  id: string;
  workspace: string;
  document?: string;
  status: string;
  decision: string;
  decision_reason: string;
  eval_cases_count: number;
  baseline_metrics: RetrievalMetrics;
  candidate_metrics: RetrievalMetrics;
  category_breakdown: Record<string, any>;
  is_promoted: boolean;
  promoted_at: string | null;
  proposed_config?: RetrievalConfiguration;
  rollback_config?: RetrievalConfiguration;
  created_at: string;
}

export interface EndToEndEvaluationRun {
  id: string;
  workspace: string;
  workspace_name?: string;
  document?: string | null;
  document_title?: string;
  job?: string | null;
  retrieval_config?: string | null;
  baseline_run?: string | null;
  evaluation_dataset_version: string;
  embedding_model_identity: string;
  vector_index_identity: string;
  app_version: string;
  status: string;
  decision: 'PASS' | 'PASS_WITH_LIMITATIONS' | 'IMPROVEMENT_DEMONSTRATED' | 'NO_CHANGE_JUSTIFIED' | 'REGRESSION_DETECTED' | 'BLOCKED' | 'FAILED' | string;
  decision_reason: string;
  is_approved_for_promotion: boolean;
  is_active_baseline: boolean;
  promoted_at?: string | null;
  eval_cases_total: number;
  eval_cases_passed: number;
  eval_cases_unverified: number;
  retrieval_metrics: Record<string, any>;
  answer_metrics: Record<string, any>;
  governance_metrics: Record<string, any>;
  category_metrics: Record<string, any>;
  baseline_comparison: Record<string, any>;
  regressions_detected: Array<{
    metric: string;
    baseline: number;
    candidate: number;
    max_allowed_regression: number;
    regression: number;
  }>;
  proposed_actions: string[];
  duration_ms: number;
  started_at: string;
  completed_at?: string | null;
  created_at: string;
}

export interface EvaluationFailureRecord {
  id: string;
  case_id: string;
  query: string;
  category: string;
  root_cause_group: 'extraction' | 'chunking' | 'metadata' | 'retrieval' | 'governance' | 'generation' | 'unverified_ground_truth' | string;
  failure_detail: string;
  expected_behavior: Record<string, any>;
  actual_behavior: Record<string, any>;
  proposed_remedy: string;
  created_at: string;
}

export interface IngestionJob {
  id: string;
  document: string;
  document_title: string;
  document_type: string;
  ocr_confidence: number;
  status: string;
  current_stage: string;
  stage_timings: Record<string, number>;
  pipeline_summary?: Record<string, any>;
  pipeline_runs?: PipelineRun[];
  error_message: string;
  error_category: string;
  attempt_count: number;
  max_retries: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ZipImportEntry {
  id: string;
  entry_path: string;
  sanitized_filename: string;
  file_size: number;
  compressed_size: number;
  file_hash: string;
  mime_type: string;
  document_type: string;
  is_supported: boolean;
  is_nested_archive: boolean;
  is_private?: boolean;
  skip_reason: string;
  status: 'pending' | 'imported' | 'failed' | 'skipped' | 'cancelled';
  document_id: string | null;
  ingestion_job_id: string | null;
  error_message: string;
  created_at: string;
  updated_at: string;
}

export interface ZipImportJob {
  id: string;
  organization: string;
  workspace: string;
  workspace_name: string;
  collection: string | null;
  collection_name: string | null;
  owner: number | null;
  owner_username: string;
  archive_filename: string;
  archive_size: number;
  archive_hash: string;
  is_slack_export?: boolean;
  status: 'pending' | 'previewed' | 'processing' | 'completed' | 'partial_success' | 'failed' | 'cancelled';
  total_entries: number;
  supported_entries: number;
  unsupported_entries: number;
  success_count: number;
  failed_count: number;
  skipped_count: number;
  authority_level: number;
  description: string;
  error_message: string;
  entries: ZipImportEntry[];
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface EmailAccountConnection {
  id: string;
  organization: string;
  workspace: string;
  workspace_name: string;
  user: number;
  user_username: string;
  provider: 'gmail' | 'outlook';
  email_address: string;
  account_name: string;
  status: 'connected' | 'syncing' | 'error' | 'disconnected';
  scopes: string[];
  last_sync_at: string | null;
  last_sync_status: string;
  last_error: string;
  total_messages_synced: number;
  created_at: string;
  updated_at: string;
}

export interface EmailSyncJob {
  id: string;
  connection: string;
  workspace: string;
  status: 'queued' | 'running' | 'completed' | 'partial_success' | 'failed' | 'cancelled';
  messages_detected: number;
  messages_imported: number;
  attachments_imported: number;
  errors: string[];
  duration_ms: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface Citation {
  citation_id: string;
  document_id: string;
  document_title: string;
  document_version: number;
  page_number?: number | null;
  section?: string | null;
  heading_path?: string;
  passage: string;
  shortest_passage?: string;
  authority_level: number;
  document_status?: 'approved' | 'draft' | 'archived' | 'superseded' | 'future-effective' | 'unknown';
  effective_date?: string | null;
  supersession_details?: string | null;
  applicability_explanation?: string;
  evidence_type?: 'direct' | 'inference';
  limitation?: string | null;
  supported_claim?: string | null;
  claim_supported?: string | null;
  score?: number;
  graph_expanded?: boolean;
  graph_depth?: number;
  traversed_relationship?: string;
  edge_provenance?: string;
  graph_path?: any[];
}

export interface ScopedExceptionResult {
  id?: string;
  name: string;
  rule_code: string;
  scope_type: string;
  scope_value: string;
  action: string;
  override_state?: string;
  justification: string;
  approved_by?: string;
}

export interface LayerBreakdown {
  l7_permission: {
    status: 'passed' | 'denied';
    denials: string[];
  };
  l1_decision_intelligence: {
    decision_type: string;
    escalation: string;
    risk: string;
  };
  l6_authority: {
    conflicts_count: number;
    unresolved_tie: boolean;
  };
  l5_temporal: {
    stale_data: boolean;
    temporal_notes: string[];
  };
  l4_exceptions: {
    applied_count: number;
    exceptions: ScopedExceptionResult[];
  };
  l3_sufficiency: {
    is_sufficient: boolean;
    missing_count: number;
  };
  l2_answer_state: {
    final_state: string;
    directive: string;
  };
  l0_observability: {
    trace_id: string;
    timings_ms: Record<string, number>;
  };
}

export interface GovernanceLayerDef {
  layer: string;
  name: string;
  decides: string;
  status: string;
  mechanism: string;
  capabilities?: string[];
  catalog?: Record<string, any>;
  precedence_ladder?: Array<{ state: string; directive: string; precedence: number }>;
}

export interface GovernanceLayersStatus {
  status: string;
  total_layers: number;
  layers_built: number;
  compliance: string;
  specification: string;
  layers: GovernanceLayerDef[];
  timestamp: string;
}

export interface GovernedResult {
  schema: string;
  state: 'denied' | 'violation' | 'conflicting' | 'insufficient' | 'abstain' | 'human_review' | 'qualified' | 'supported' | 'no_knowledge';
  directive: 'stop' | 'ask_user' | 'escalate' | 'proceed_and_cite' | 'proceed';
  answer: string;
  decision_type: string;
  escalation_target?: string;
  risk_level?: string;
  evidence_found: Array<{
    document_id: string;
    document_title: string;
    authority_level: number;
    page_number: number;
    score: number;
    heading: string;
    snippet: string;
  }>;
  evidence_missing: Array<{
    requirement: string;
    mandatory: boolean;
    status: string;
    description: string;
  }>;
  conflicts_resolved: Array<{
    informal_claim?: string;
    authoritative_source?: string;
    resolution?: string;
    note?: string;
  }>;
  exceptions_applied?: ScopedExceptionResult[];
  citations: Citation[];
  notes: string[];
  decision_id: string;
  trace_id: string;
  token_count: number;
  llm_provider?: string;
  llm_model?: string;
  anti_hallucination_active?: boolean;
  layers_breakdown?: LayerBreakdown;
  validation_signals?: {
    source_provenance: boolean;
    relevance: boolean;
    entailment: boolean;
    authority: boolean;
    conflict: boolean;
    audit_provenance_verified: boolean;
    zero_hallucination: boolean;
  };
  audit_id?: string;
}

export interface AuditEvent {
  id: string;
  username: string;
  event_type: string;
  target_type: string;
  target_id: string;
  details: Record<string, any>;
  created_at: string;
}

export interface ChatMessage {
  id: string;
  conversation: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  sequence_number: number;
  status: 'pending' | 'completed' | 'failed' | 'retrying';
  error_message?: string;
  client_message_id?: string;
  governance_state?: string;
  governance_directive?: string;
  trace_id?: string;
  citations?: Citation[];
  revalidated_citations?: Citation[];
  evidence_missing?: Array<{ requirement: string; mandatory?: boolean; status?: string; explanation?: string }>;
  conflicts_resolved?: any[];
  layers_breakdown?: LayerBreakdown;
  retrieval_config?: {
    document_id?: string | null;
    collection_id?: string | null;
  };
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  document_id?: string | null;
  collection_id?: string | null;
  message_count: number;
  last_query_snippet?: string;
  last_activity_at: string;
  created_at: string;
  updated_at: string;
  is_archived: boolean;
}

export interface ConversationDetail {
  id: string;
  title: string;
  document_id?: string | null;
  collection_id?: string | null;
  message_count: number;
  last_activity_at: string;
  created_at: string;
  updated_at: string;
  is_archived: boolean;
  messages: ChatMessage[];
}

class ApiClient {
  private token: string | null = null;

  constructor() {
    if (typeof window !== 'undefined') {
      this.token = localStorage.getItem('lore_token');
    }
  }

  setToken(token: string) {
    this.token = token;
    if (typeof window !== 'undefined') {
      localStorage.setItem('lore_token', token);
    }
  }

  clearToken() {
    this.token = null;
    if (typeof window !== 'undefined') {
      localStorage.removeItem('lore_token');
    }
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${API_BASE}${endpoint}`;
    const headers = new Headers(options.headers || {});

    const isPublicAuthEndpoint = endpoint.includes('/identity/login') || endpoint.includes('/identity/register');
    if (this.token && !isPublicAuthEndpoint) {
      headers.set('Authorization', `Token ${this.token}`);
    }

    if (!(options.body instanceof FormData) && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }

    const response = await fetch(url, { ...options, headers });
    if (!response.ok) {
      if (response.status === 401) {
        this.clearToken();
      }
      let errDetail = response.statusText;
      try {
        const errJson = await response.json();
        errDetail = errJson.error || errJson.detail || JSON.stringify(errJson);
      } catch (e) {
        // ignore
      }
      throw new Error(`API Error [${response.status}]: ${errDetail}`);
    }

    return response.json();
  }

  // Auth
  async login(username: string, password: string) {
    this.clearToken();
    const res = await this.request<{ token: string; user: User; organizations: Organization[] }>('/identity/login/', {
      method: 'POST',
      body: JSON.stringify({ username, password })
    });
    this.setToken(res.token);
    return res;
  }

  async me() {
    return this.request<{ user: User; organizations: Organization[] }>('/identity/me/');
  }

  // Workspaces & Collections
  async getWorkspaces(orgId?: string) {
    const query = orgId ? `?organization_id=${orgId}` : '';
    const res = await this.request<any>(`/workspaces/workspaces/${query}`);
    return Array.isArray(res) ? res : res.results || [];
  }

  async getCollections(workspaceId?: string) {
    const query = workspaceId ? `?workspace_id=${workspaceId}` : '';
    const res = await this.request<any>(`/workspaces/collections/${query}`);
    return Array.isArray(res) ? res : res.results || [];
  }

  // Documents
  async getDocuments(workspaceId: string, status?: string, collectionId?: string) {
    let query = `?workspace_id=${workspaceId}`;
    if (status) query += `&status=${status}`;
    if (collectionId) query += `&collection_id=${collectionId}`;
    const res = await this.request<any>(`/sources/documents/${query}`);
    return Array.isArray(res) ? res : res.results || [];
  }

  async getDocument(id: string) {
    return this.request<SourceDocument>(`/sources/documents/${id}/`);
  }

  async getDocumentPages(id: string) {
    return this.request<DocumentPage[]>(`/sources/documents/${id}/pages/`);
  }

  async uploadDocument(formData: FormData) {
    return this.request<{
      document?: SourceDocument;
      job_id?: string;
      status?: string;
      documents?: SourceDocument[];
      job_ids?: string[];
      jobs?: Array<{ document_id: string; job_id: string; status: string }>;
      count?: number;
      errors?: Array<{ filename: string; error: string }>;
    }>('/sources/documents/', {
      method: 'POST',
      body: formData
    });
  }

  async bulkUploadDocuments(formData: FormData) {
    return this.request<{
      status: string;
      total_count: number;
      success_count: number;
      failed_count: number;
      successful: Array<{ document: SourceDocument; job_id: string; status: string }>;
      failed: Array<{ filename: string; error: string }>;
      documents: SourceDocument[];
      job_ids: string[];
      document?: SourceDocument;
      job_id?: string;
      doc_status?: string;
    }>('/sources/documents/bulk-upload/', {
      method: 'POST',
      body: formData
    });
  }

  // ZIP Archive Ingestion Engine
  async previewZipArchive(formData: FormData): Promise<ZipImportJob> {
    return this.request<ZipImportJob>('/sources/zip-imports/preview/', {
      method: 'POST',
      body: formData
    });
  }

  async startZipImport(jobId: string): Promise<ZipImportJob> {
    return this.request<ZipImportJob>(`/sources/zip-imports/${jobId}/start/`, {
      method: 'POST'
    });
  }

  async getZipImportJob(jobId: string): Promise<ZipImportJob> {
    return this.request<ZipImportJob>(`/sources/zip-imports/${jobId}/`);
  }

  async cancelZipImport(jobId: string): Promise<ZipImportJob> {
    return this.request<ZipImportJob>(`/sources/zip-imports/${jobId}/cancel/`, {
      method: 'POST'
    });
  }

  async retryZipImport(jobId: string): Promise<ZipImportJob> {
    return this.request<ZipImportJob>(`/sources/zip-imports/${jobId}/retry/`, {
      method: 'POST'
    });
  }

  async getZipImportSummary(jobId: string): Promise<any> {
    return this.request<any>(`/sources/zip-imports/${jobId}/summary/`);
  }

  getZipImportSummaryCsvUrl(jobId: string): string {
    return `${API_BASE}/sources/zip-imports/${jobId}/summary/?export=csv`;
  }

  async reprocessDocument(id: string) {
    return this.request<{ message: string; job_id: string }>(`/sources/documents/${id}/reprocess/`, {
      method: 'POST'
    });
  }

  async liveOCR(formData: FormData) {
    return this.request<{
      status: string;
      filename: string;
      file_hash: string;
      document_type: string;
      pages: DocumentPage[];
      page_count: number;
      ocr_confidence: number;
      total_words: number;
      timings_ms: number;
      document_id: string | null;
    }>('/sources/documents/live-ocr/', {
      method: 'POST',
      body: formData
    });
  }

  // Ingestion Jobs
  async getJobs(workspaceId: string) {
    const res = await this.request<any>(`/ingestion/jobs/?workspace_id=${workspaceId}`);
    return Array.isArray(res) ? res : res.results || [];
  }

  async getJob(id: string) {
    return this.request<IngestionJob>(`/ingestion/jobs/${id}/`);
  }

  async retryJob(id: string) {
    return this.request<IngestionJob>(`/ingestion/jobs/${id}/retry/`, {
      method: 'POST'
    });
  }

  // Retrieval & Governed RAG
  async governedQuery(
    workspaceId: string, 
    query: string, 
    collectionId?: string,
    documentId?: string,
    groqApiKey?: string,
    llmModel?: string,
    conversationId?: string,
    clientMessageId?: string
  ) {
    const activeGroqKey = groqApiKey || (typeof window !== 'undefined' ? localStorage.getItem('lore_groq_api_key') : null) || undefined;
    const activeModel = llmModel || (typeof window !== 'undefined' ? localStorage.getItem('lore_llm_model') : null) || 'gpt-oss-120B';

    return this.request<GovernedResult & { conversation_id?: string; conversation_title?: string; user_message_id?: string; assistant_message_id?: string }>('/retrieval/query/', {
      method: 'POST',
      body: JSON.stringify({ 
        workspace: workspaceId, 
        query, 
        collection: collectionId,
        document_id: documentId,
        groq_api_key: activeGroqKey,
        llm_model: activeModel,
        conversation_id: conversationId,
        save_conversation: true,
        client_message_id: clientMessageId
      })
    });
  }

  // Persistent Chat History & Conversations
  async getConversations(workspaceId: string, search?: string, archived?: boolean): Promise<ConversationSummary[]> {
    let url = `/decisions/conversations/?workspace=${workspaceId}`;
    if (search && search.trim()) {
      url += `&search=${encodeURIComponent(search.trim())}`;
    }
    if (archived !== undefined) {
      url += `&archived=${archived}`;
    }
    const res = await this.request<{ count: number; results: ConversationSummary[] } | ConversationSummary[]>(url);
    return Array.isArray(res) ? res : res.results || [];
  }

  async getConversation(id: string): Promise<ConversationDetail> {
    return this.request<ConversationDetail>(`/decisions/conversations/${id}/`);
  }

  async createConversation(workspaceId: string, title?: string, documentId?: string, collectionId?: string): Promise<ConversationDetail> {
    return this.request<ConversationDetail>('/decisions/conversations/', {
      method: 'POST',
      body: JSON.stringify({
        workspace: workspaceId,
        title: title || 'New Conversation',
        document_id: documentId,
        collection_id: collectionId
      })
    });
  }

  async renameConversation(id: string, title: string): Promise<{ id: string; title: string }> {
    return this.request<{ id: string; title: string }>(`/decisions/conversations/${id}/`, {
      method: 'PATCH',
      body: JSON.stringify({ title })
    });
  }

  async deleteConversation(id: string): Promise<{ status: string; id: string }> {
    return this.request<{ status: string; id: string }>(`/decisions/conversations/${id}/`, {
      method: 'DELETE'
    });
  }

  async sendConversationMessage(
    conversationId: string,
    query: string,
    options?: {
      clientMessageId?: string;
      documentId?: string;
      collectionId?: string;
      groqApiKey?: string;
      llmModel?: string;
    }
  ): Promise<{
    conversation_id: string;
    conversation_title?: string;
    user_message: ChatMessage;
    assistant_message: ChatMessage;
    result: GovernedResult;
  }> {
    const activeGroqKey = options?.groqApiKey || (typeof window !== 'undefined' ? localStorage.getItem('lore_groq_api_key') : null) || undefined;
    const activeModel = options?.llmModel || (typeof window !== 'undefined' ? localStorage.getItem('lore_llm_model') : null) || 'gpt-oss-120B';

    return this.request(`/decisions/conversations/${conversationId}/messages/`, {
      method: 'POST',
      body: JSON.stringify({
        query,
        client_message_id: options?.clientMessageId || `msg_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
        document_id: options?.documentId,
        collection_id: options?.collectionId,
        groq_api_key: activeGroqKey,
        llm_model: activeModel
      })
    });
  }

  async testGroqConnection(apiKey: string, model: string = 'gpt-oss-120B') {
    return this.request<{
      status: string;
      provider: string;
      requested_model: string;
      model_available: boolean;
      models_count: number;
      latency_ms: number;
      anti_hallucination: string;
      default_temperature: number;
      message: string;
    }>('/retrieval/test-groq/', {
      method: 'POST',
      body: JSON.stringify({ api_key: apiKey, model })
    });
  }

  async search(workspaceId: string, query: string, limit: number = 8) {
    return this.request<{ results: any[] }>('/retrieval/search/', {
      method: 'POST',
      body: JSON.stringify({ workspace: workspaceId, query, limit })
    });
  }

  // Review Queue
  async getReviewQueue(workspaceId: string) {
    const res = await this.request<any>(`/governance/review/?workspace_id=${workspaceId}`);
    return Array.isArray(res) ? res : res.results || [];
  }

  async approveDocument(id: string) {
    return this.request<{ message: string; status: string }>(`/governance/review/${id}/approve/`, {
      method: 'POST'
    });
  }

  async rejectDocument(id: string) {
    return this.request<{ message: string; status: string }>(`/governance/review/${id}/reject/`, {
      method: 'POST'
    });
  }

  // Audit
  async getAuditEvents(workspaceId: string) {
    const res = await this.request<any>(`/audit/events/?workspace_id=${workspaceId}`);
    return Array.isArray(res) ? res : res.results || [];
  }

  // 9-Layer Governance Stack (LORE Architecture v3.0 §3, §4, §10)
  async getGovernanceLayersStatus(): Promise<GovernanceLayersStatus> {
    return this.request<GovernanceLayersStatus>('/governance/layers/');
  }

  async getScopedExceptions(workspaceId?: string) {
    const q = workspaceId ? `?workspace_id=${workspaceId}` : '';
    const res = await this.request<any>(`/governance/exceptions/${q}`);
    return Array.isArray(res) ? res : res.results || [];
  }

  async createScopedException(data: {
    workspace_id: string;
    name: string;
    rule_code: string;
    scope_type: string;
    scope_value: string;
    action?: string;
    override_state?: string;
    justification: string;
    valid_from?: string;
    valid_until?: string;
  }) {
    return this.request<any>('/governance/exceptions/', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  }

  async getEvidenceRequirements(workspaceId?: string) {
    const q = workspaceId ? `?workspace_id=${workspaceId}` : '';
    const res = await this.request<any>(`/governance/requirements/${q}`);
    return Array.isArray(res) ? res : res.results || [];
  }

  // SaaS Subscriptions & Quotas
  async getPlans(): Promise<Plan[]> {
    return this.request<Plan[]>('/subscriptions/plans/');
  }

  async getSubscription(orgId?: string): Promise<SubscriptionData> {
    const query = orgId ? `?organization_id=${orgId}` : '';
    return this.request<SubscriptionData>(`/subscriptions/subscription/${query}`);
  }

  async changePlan(orgId: string, planSlug: string): Promise<{ checkout_url: string }> {
    return this.request<{ checkout_url: string }>('/subscriptions/subscription/', {
      method: 'POST',
      body: JSON.stringify({ organization_id: orgId, plan_slug: planSlug })
    });
  }

  // Organization Management & Invitations
  async getOrgMembers(orgId: string): Promise<OrganizationMember[]> {
    const res = await this.request<any>(`/identity/organizations/${orgId}/members/`);
    return Array.isArray(res) ? res : res.results || [];
  }

  async removeOrgMember(orgId: string, membershipId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/identity/organizations/${orgId}/members/${membershipId}/`, {
      method: 'DELETE'
    });
  }

  async getOrgInvitations(orgId: string): Promise<OrganizationInvitation[]> {
    const res = await this.request<any>(`/identity/organizations/${orgId}/invitations/`);
    return Array.isArray(res) ? res : res.results || [];
  }

  async createOrgInvitation(orgId: string, email: string, role: string): Promise<OrganizationInvitation> {
    return this.request<OrganizationInvitation>(`/identity/organizations/${orgId}/invitations/`, {
      method: 'POST',
      body: JSON.stringify({ email, role })
    });
  }

  async acceptInvitation(token: string): Promise<{ message: string }> {
    return this.request<{ message: string }>('/identity/invitations/accept/', {
      method: 'POST',
      body: JSON.stringify({ token })
    });
  }

  // Email Connectors & OAuth API
  async getEmailConnections(workspaceId: string): Promise<EmailAccountConnection[]> {
    const res = await this.request<any>(`/sources/email/connections/?workspace=${workspaceId}`);
    return Array.isArray(res) ? res : res.results || [];
  }

  async getEmailOAuthAuthorizeUrl(workspaceId: string, provider: string = 'gmail'): Promise<{
    provider: string;
    authorization_url: string;
    state: string;
    scope: string;
    redirect_uri: string;
  }> {
    return this.request(`/sources/email/oauth/authorize/?workspace=${workspaceId}&provider=${provider}`);
  }

  async triggerEmailSync(connectionId: string, fullSync: boolean = false, maxMessages: number = 50): Promise<any> {
    return this.request(`/sources/email/connections/${connectionId}/sync/`, {
      method: 'POST',
      body: JSON.stringify({ full_sync: fullSync, max_messages: maxMessages })
    });
  }

  async disconnectEmailConnection(connectionId: string, retainContent: boolean = true): Promise<any> {
    return this.request(`/sources/email/connections/${connectionId}/disconnect/`, {
      method: 'POST',
      body: JSON.stringify({ retain_content: retainContent })
    });
  }

  async getEmailConnectionJobs(connectionId: string): Promise<EmailSyncJob[]> {
    const res = await this.request<any>(`/sources/email/connections/${connectionId}/jobs/`);
    return Array.isArray(res) ? res : res.results || [];
  }

  async logout(): Promise<void> {
    try {
      await this.request('/identity/logout/', { method: 'POST' });
    } catch (e) {
      // Continue clearing local token even if request fails
    }
    this.clearToken();
  }

  async register(username: string, email: string, password: string, organizationName?: string) {
    const res = await this.request<{ token: string; user: User; organization: Organization }>('/identity/register/', {
      method: 'POST',
      body: JSON.stringify({
        username,
        email,
        password,
        organization_name: organizationName
      })
    });
    this.setToken(res.token);
    return res;
  }

  // Evidence-Driven Retrieval Optimization (Run 3)
  async getRetrievalConfigurations(workspaceId: string) {
    return this.request<{
      workspace_id: string;
      active_configuration: RetrievalConfiguration;
      configurations: RetrievalConfiguration[];
    }>(`/retrieval/configurations/?workspace=${workspaceId}`);
  }

  async runRetrievalOptimization(workspaceId: string, customCases?: any[]) {
    return this.request<{
      status: string;
      optimization_run_id: string;
      decision: string;
      decision_reason: string;
      eval_cases_count: number;
      baseline_metrics: RetrievalMetrics;
      candidate_metrics: RetrievalMetrics;
      category_breakdown: Record<string, any>;
      proposed_config?: RetrievalConfiguration;
    }>('/retrieval/configurations/', {
      method: 'POST',
      body: JSON.stringify({ workspace: workspaceId, custom_cases: customCases })
    });
  }

  async promoteRetrievalConfiguration(optimizationRunId: string) {
    return this.request<{
      status: string;
      promoted_configuration: RetrievalConfiguration;
      message: string;
    }>('/retrieval/configurations/promote/', {
      method: 'POST',
      body: JSON.stringify({ optimization_run_id: optimizationRunId })
    });
  }

  async rollbackRetrievalConfiguration(workspaceId: string, targetConfigId?: string) {
    return this.request<{
      status: string;
      active_configuration: RetrievalConfiguration;
      message: string;
    }>('/retrieval/configurations/rollback/', {
      method: 'POST',
      body: JSON.stringify({ workspace: workspaceId, target_config_id: targetConfigId })
    });
  }

  async getRetrievalOptimizationRuns(workspaceId: string) {
    return this.request<{
      workspace_id: string;
      runs: RetrievalOptimizationRun[];
    }>(`/retrieval/optimizations/?workspace=${workspaceId}`);
  }

  // End-to-End Final Evaluation, Regression Testing & Continuous Improvement (Run 4)
  async getEvaluations(workspaceId: string) {
    return this.request<{
      workspace_id: string;
      active_baseline: EndToEndEvaluationRun | null;
      evaluations: EndToEndEvaluationRun[];
    }>(`/governance/evaluations/?workspace=${workspaceId}`);
  }

  async getEvaluationDetail(runId: string) {
    return this.request<EndToEndEvaluationRun>(`/governance/evaluations/${runId}/`);
  }

  async getEvaluationCategories(runId: string) {
    return this.request<{
      evaluation_run_id: string;
      decision: string;
      category_metrics: Record<string, any>;
    }>(`/governance/evaluations/${runId}/categories/`);
  }

  async getEvaluationFailures(runId: string) {
    return this.request<{
      evaluation_run_id: string;
      total_failures: number;
      grouped_by_root_cause: Record<string, EvaluationFailureRecord[]>;
    }>(`/governance/evaluations/${runId}/failures/`);
  }

  async compareEvaluations(runAId: string, runBId: string) {
    return this.request<any>(`/governance/evaluations/compare/?run_a=${runAId}&run_b=${runBId}`);
  }

  async getEvaluationBaseline(workspaceId: string) {
    return this.request<{
      workspace_id: string;
      active_baseline: EndToEndEvaluationRun | null;
    }>(`/governance/evaluations/baseline/?workspace=${workspaceId}`);
  }

  async promoteEvaluationBaseline(runId: string) {
    return this.request<{
      status: string;
      promoted_run_id: string;
      message: string;
    }>(`/governance/evaluations/${runId}/promote/`, {
      method: 'POST'
    });
  }

  async rollbackEvaluationBaseline(workspaceId: string, targetRunId?: string) {
    return this.request<{
      status: string;
      active_baseline_id: string;
      message: string;
    }>('/governance/evaluations/rollback/', {
      method: 'POST',
      body: JSON.stringify({ workspace: workspaceId, target_run_id: targetRunId })
    });
  }

  async runEvaluation(workspaceId: string, customCases?: any[], datasetVersion?: string) {
    return this.request<EndToEndEvaluationRun>('/governance/evaluations/', {
      method: 'POST',
      body: JSON.stringify({ workspace: workspaceId, custom_cases: customCases, dataset_version: datasetVersion })
    });
  }
}

export interface Plan {
  id: string;
  name: string;
  slug: string;
  description: string;
  price_monthly: number;
  max_storage_mb: number;
  max_documents: number;
  max_monthly_queries: number;
  max_workspaces: number;
  max_members: number;
  allow_custom_models: boolean;
  allow_ocr_bengali: boolean;
  allow_audit_export: boolean;
}

export interface SubscriptionData {
  subscription: {
    id: string;
    organization: string;
    plan: Plan | null;
    status: string;
    stripe_customer_id: string;
    stripe_subscription_id: string;
    cancel_at_period_end: boolean;
  };
  usage: {
    period_key: string;
    storage_bytes: number;
    storage_mb: number;
    documents_count: number;
    queries_count: number;
    tokens_used: number;
  };
  quotas: {
    max_storage_mb: number;
    max_documents: number;
    max_monthly_queries: number;
  };
}

export interface OrganizationMember {
  id: string;
  organization: string;
  user: User;
  role: string;
  joined_at: string;
}

export interface OrganizationInvitation {
  id: string;
  organization: string;
  organization_name: string;
  email: string;
  role: string;
  invited_by_username: string;
  token: string;
  expires_at: string;
  is_accepted: boolean;
  is_expired: boolean;
  created_at: string;
}

export const api = new ApiClient();

// Explicit bindings to guarantee prototype availability across Turbopack HMR sessions
api.getConversations = api.getConversations.bind(api);
api.getConversation = api.getConversation.bind(api);
api.createConversation = api.createConversation.bind(api);
api.renameConversation = api.renameConversation.bind(api);
api.deleteConversation = api.deleteConversation.bind(api);
api.sendConversationMessage = api.sendConversationMessage.bind(api);

