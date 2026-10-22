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

export interface GovernedResult {
  schema: string;
  state: 'denied' | 'violation' | 'conflicting' | 'insufficient' | 'abstain' | 'human_review' | 'qualified' | 'supported' | 'no_knowledge';
  directive: 'stop' | 'ask_user' | 'escalate' | 'proceed_and_cite' | 'proceed';
  answer: string;
  decision_type: string;
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
  citations: Citation[];
  notes: string[];
  decision_id: string;
  trace_id: string;
  token_count: number;
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
    return this.request<{ document: SourceDocument; job_id: string; status: string }>('/sources/documents/', {
      method: 'POST',
      body: formData
    });
  }

  async reprocessDocument(id: string) {
    return this.request<{ message: string; job_id: string }>(`/sources/documents/${id}/reprocess/`, {
      method: 'POST'
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
  async governedQuery(workspaceId: string, query: string, collectionId?: string) {
    return this.request<GovernedResult>('/retrieval/query/', {
      method: 'POST',
      body: JSON.stringify({ workspace: workspaceId, query, collection: collectionId })
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
}

export const api = new ApiClient();
