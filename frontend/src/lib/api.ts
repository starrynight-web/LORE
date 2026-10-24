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

export interface IngestionJob {
  id: string;
  document: string;
  document_title: string;
  document_type: string;
  ocr_confidence: number;
  status: string;
  current_stage: string;
  stage_timings: Record<string, number>;
  error_message: string;
  error_category: string;
  attempt_count: number;
  max_retries: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Citation {
  citation_id: string;
  document_id: string;
  document_title: string;
  document_version: number;
  page_number: number;
  heading_path: string;
  passage: string;
  authority_level: number;
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

    if (this.token) {
      headers.set('Authorization', `Token ${this.token}`);
    }

    if (!(options.body instanceof FormData) && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }

    const response = await fetch(url, { ...options, headers });
    if (!response.ok) {
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
    llmModel?: string
  ) {
    const activeGroqKey = groqApiKey || (typeof window !== 'undefined' ? localStorage.getItem('lore_groq_api_key') : null) || undefined;
    const activeModel = llmModel || (typeof window !== 'undefined' ? localStorage.getItem('lore_llm_model') : null) || 'gpt-oss-120B';

    return this.request<GovernedResult>('/retrieval/query/', {
      method: 'POST',
      body: JSON.stringify({ 
        workspace: workspaceId, 
        query, 
        collection: collectionId,
        document_id: documentId,
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

