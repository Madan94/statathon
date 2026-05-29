import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { isAuthRoute, PUBLIC_ROUTES } from './authConfig';
import { redirectToLogin } from './authSession';
import { getCsrfToken } from './csrf';

/** Browser uses same-origin proxy so httpOnly cookies are set on the dashboard host. */
function resolveApiBase(): string {
  if (typeof window !== 'undefined') {
    return '/api/backend';
  }
  return (
    process.env.API_INTERNAL_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    'http://127.0.0.1:8000'
  );
}

const API_BASE = resolveApiBase();

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
});

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const method = (config.method || 'get').toUpperCase();
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    const csrf = getCsrfToken();
    if (csrf) {
      config.headers.set('X-CSRF-Token', csrf);
    }
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean };
    if (
      error.response?.status === 401 &&
      original &&
      !original._retry &&
      !original.url?.includes('/auth/login') &&
      !original.url?.includes('/auth/signup') &&
      !original.url?.includes('/auth/refresh')
    ) {
      original._retry = true;
      try {
        await api.post('/auth/refresh');
        return api(original);
      } catch {
        if (typeof window !== 'undefined') {
          const path = window.location.pathname;
          const isPublic = (PUBLIC_ROUTES as readonly string[]).includes(path);
          if (!isPublic && !isAuthRoute(path)) {
            redirectToLogin(path);
          }
        }
      }
    }
    return Promise.reject(error);
  }
);

export interface AuthUser {
  id: number;
  email: string;
  full_name: string | null;
  officer_role: string | null;
  email_verified_at: string | null;
}

export interface ChallengeResponse {
  challenge_id: string;
  expires_in: number;
  dev_otp_logged?: boolean;
}

// ─── Column / analysis-pipeline types ───────────────────────────────────────

export interface ColumnProfile {
  datatype: string;
  missing_ratio: number;
  missing_count?: number;
  cardinality: number;
  unique_ratio?: number;
  entropy?: number;
  skewness?: number;
  top_values?: Array<[string, number] | { value: unknown; count: number }>;
  sample_values?: unknown[];
  semantic_hints?: string[];
  mean_std?: { mean: number; std: number };
  min_max?: { min: number; max: number };
}

export interface AnalysisSummaryPayload {
  meta: Record<string, unknown>;
  dataset_context: Record<string, unknown>;
  dataset_profile: Record<string, unknown>;
  dataset_name: string;
  column_profiles_keys: string[];
  profiling_summary: {
    health?: {
      rows: number;
      columns: number;
      missing_per_column?: Record<string, number>;
      dtypes?: Record<string, string>;
    };
    schema?: Record<string, string>;
  };
}

export interface DomainInfo {
  description?: string;
  examples?: string[];
  sub_domains?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DomainsPayload {
  meta: Record<string, unknown>;
  dataset_context: Record<string, unknown>;
  static_domains_taxonomy: Record<string, DomainInfo>;
  domain_registry?: DomainRegistry;
  ontology_macro_type_best_hint?: string;
}

export interface ClusterGroup {
  cluster_id: string;
  domain: string;
  support_score: number;
  support?: number;
  columns: string[];
  domain_distribution?: Record<string, number>;
  embedding_coherence?: number;
  domain_purity?: number;
  avg_domain_confidence?: number;
}

export interface ClustersPayload {
  meta: Record<string, unknown>;
  clusters: ClusterGroup[];
}

export interface GraphNode {
  name: string;
  [key: string]: unknown;
}

export interface GraphEdge {
  source: string;
  target: string;
  weight?: number;
  relationship_type?: string;
  owl_type?: string;
  owl_label?: string;
  semantic_reason?: string;
  source_domain?: string;
  target_domain?: string;
}

export interface GraphPayload {
  meta: Record<string, unknown>;
  nodes: GraphNode[];
  edges: GraphEdge[];
  priority_dependencies?: unknown;
  dataset_metadata?: Record<string, unknown>;
}

export interface AnomalyExplain {
  primary_method?: string;
  metric?: number | null;
  isolation_forest?: boolean;
}

export interface AnomalyCandidate {
  row: number;
  column: string;
  value: unknown;
  method: string;
  confidence: number;
  severity: string;
  candidate_action: string;
  alternate_actions?: string[];
  explain?: string | AnomalyExplain;
}

// ─────────────────────────────────────────────────────────────────────────────

export interface DatasetHealthSummary {
  rows?: number;
  columns?: number;
  missing_cells?: number;
  duplicate_rows?: number;
  numeric_columns?: number;
  categorical_columns?: number;
  column_list?: string[];
  dtypes?: Record<string, string>;
  missing_per_column?: Record<string, number>;
  memory_usage_mb?: number;
  completeness_pct?: number;
  consistency_pct?: number;
  preview_rows?: Record<string, unknown>[];
}

export interface UploadResponse {
  dataset_id: number;
  id: number;
  filename: string;
  name?: string;
  row_count: number;
  column_count: number;
  file_size?: number;
  file_size_bytes?: number;
  file_size_mb?: number;
  uploaded_at?: string;
  status: string;
  upload_status?: string;
  health_summary?: DatasetHealthSummary;
  missing_cells?: number;
  duplicate_rows?: number;
  numeric_columns?: number;
  categorical_columns?: number;
  column_list?: string[];
  memory_usage_mb?: number;
  completeness_pct?: number;
  consistency_pct?: number;
  preview_rows?: Record<string, unknown>[];
  analysis_id?: number;
}

export interface PresignedUploadResponse {
  upload_url: string;
  object_key: string;
  expires_in: number;
}

export interface Dataset {
  id: number;
  filename: string;
  name?: string;
  row_count: number;
  column_count: number;
  status: string;
  created_at: string;
  uploaded_at?: string;
  file_size?: number;
  file_size_bytes?: number;
  file_size_mb?: number;
  upload_status?: string;
  storage_provider?: string;
  object_key?: string;
  checksum?: string;
  health_summary?: DatasetHealthSummary | null;
  missing_cells?: number;
  duplicate_rows?: number;
  numeric_columns?: number;
  categorical_columns?: number;
  column_list?: string[];
  memory_usage_mb?: number;
  completeness_pct?: number;
  consistency_pct?: number;
  preview_rows?: Record<string, unknown>[];
}

export interface Analysis {
  id: number;
  analysis_id?: number;
  dataset_id: number;
  status: string;
  created_at?: string;
  completed_at?: string;
}

export interface AnalysisStatus {
  analysis_id: number;
  dataset_id: number;
  status: string;
  error_message?: string;
  completed_at?: string;
}

export interface SemanticMappingRow {
  column: string;
  domain?: string;
  confidence?: number;
  cluster_id?: string;
  normalized_name?: string;
  routing_path?: string;
  matched_keyword?: string;
  dynamic_cohesion?: number;
  cluster_support?: number;
  graph_consistency?: number;
  explainability?: {
    matching_reason?: string;
    dataset_archetype?: string;
    match_method?: string;
    is_locked?: boolean;
  };
  top_domain_scores?: Record<string, number>;
  [key: string]: unknown;
}

export interface DomainRegistryEntry {
  label?: string;
  domains?: string[];
  keywords_sample?: Record<string, string[]>;
  parent_theme?: string;
  members?: string[];
  cohesion?: number;
  keywords?: string[];
  is_dynamic?: boolean;
}

export interface DomainRegistry {
  active_archetype?: string;
  universal_domains?: string[];
  static_ontology?: Record<string, DomainRegistryEntry>;
  dynamic_domains?: Record<string, DomainRegistryEntry>;
}

export interface ValidationCandidate {
  column?: string;
  kind?: string;
  severity?: string;
  candidate_action?: string;
  row?: number;
}

export interface ImputationCandidate {
  column: string;
  missing_count?: number;
  recommended_method?: string;
  confidence?: number;
  confidence_band?: string;
  method_scores?: Record<string, number>;
}

export interface OutlierResult {
  column: string;
  zscore: number[];
  iqr: number[];
  confidence: number;
  risk: 'low' | 'medium' | 'high';
}

export interface WeightedProfile {
  applied?: boolean;
  weight_column?: string | null;
  weighted_numeric_means?: Record<string, number>;
  effective_sample_size?: number;
  reason?: string;
}

export interface ColumnNormalizationRow {
  original_name: string;
  normalized_name: string;
  display_name: string;
  domain?: string;
  match_method?: string;
  match_confidence?: number;
  matching_reason?: string;
  semantic_hints?: string[];
  [key: string]: unknown;
}

export interface AnalysisResult {
  analysis_id?: number;
  health?: Record<string, unknown>;
  schema?: Record<string, string>;
  semantic?: Record<string, string>;
  semantic_mapping?: SemanticMappingRow[];
  column_normalization?: ColumnNormalizationRow[];
  domain_registry?: DomainRegistry;
  dataset_context?: Record<string, unknown>;
  clusters?: Array<Record<string, unknown>>;
  schema_graph?: { nodes?: unknown[]; edges?: unknown[] };
  profiling_summary?: Record<string, unknown>;
  column_profiles?: Record<string, unknown>;
  priority_dependencies?: Record<string, unknown> | unknown[];
  phase3?: {
    validation_candidates?: ValidationCandidate[];
    imputation_candidates?: ImputationCandidate[];
    anomaly_candidates?: unknown[];
    user_decisions?: Record<string, string>;
    [key: string]: unknown;
  };
  audit_logs?: Array<Record<string, unknown>>;
  weighted_profile?: WeightedProfile;
  derived_dataset?: Record<string, unknown>;
  outliers?: Record<string, OutlierResult>;
  content_hash?: string;
}

export interface DashboardSummary {
  datasets_count: number;
  analyses_count: number;
  analyses_complete_count: number;
  reports_count: number;
  report_jobs_count: number;
  report_jobs_exported_count: number;
  latest_datasets: Array<{
    id: number;
    filename: string;
    status: string;
    row_count: number;
    column_count: number;
    created_at: string | null;
  }>;
}

export const dashboardApi = {
  getSummary: async (): Promise<DashboardSummary> => {
    const { data } = await api.get('/dashboard/summary');
    return data;
  },
};

export const authApi = {
  signupStart: async (payload: {
    full_name: string;
    officer_role: string;
    email: string;
    password: string;
  }): Promise<ChallengeResponse> => {
    const { data } = await api.post('/auth/signup/start', payload);
    return data;
  },
  signupVerifyOtp: async (challenge_id: string, otp: string) => {
    const { data } = await api.post('/auth/signup/verify-otp', { challenge_id, otp });
    return data;
  },
  signupResendOtp: async (challenge_id: string): Promise<ChallengeResponse> => {
    const { data } = await api.post('/auth/signup/resend-otp', { challenge_id });
    return data;
  },
  loginStart: async (email: string, password: string): Promise<ChallengeResponse> => {
    const { data } = await api.post('/auth/login/start', { email, password });
    return data;
  },
  loginVerifyOtp: async (challenge_id: string, otp: string) => {
    const { data } = await api.post('/auth/login/verify-otp', { challenge_id, otp });
    return data;
  },
  loginResendOtp: async (challenge_id: string): Promise<ChallengeResponse> => {
    const { data } = await api.post('/auth/login/resend-otp', { challenge_id });
    return data;
  },
  me: async (): Promise<AuthUser> => {
    const { data } = await api.get('/auth/me');
    return data;
  },
  logout: async () => {
    await api.post('/auth/logout');
  },
};

/** MIME type sent to presigned-URL signer and R2 PUT (must stay in sync). */
function datasetPresignedContentType(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase();
  if (ext === 'csv') return 'text/csv';
  if (ext === 'xls') return 'application/vnd.ms-excel';
  return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
}

export const datasetsApi = {
  upload: async (file: File): Promise<UploadResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post('/datasets/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },
  presignedUpload: async (file: File): Promise<UploadResponse> => {
    const contentType = datasetPresignedContentType(file.name);
    const { data: urlData } = await api.post<PresignedUploadResponse>('/datasets/upload-url', {
      filename: file.name,
      content_type: contentType,
    });
    let uploadResp: Response;
    try {
      uploadResp = await fetch(urlData.upload_url, {
        method: 'PUT',
        body: file,
        headers: { 'Content-Type': contentType },
      });
    } catch (e: unknown) {
      const hint =
        typeof window !== 'undefined'
          ? ' Ensure R2 CORS AllowedOrigins include both http://localhost:3000 and http://127.0.0.1:3000 (must match address bar exactly) — see docs/R2_STEP_BY_STEP.md Step 5.'
          : '';
      const msg =
        e instanceof Error
          ? `${e.message}${hint}`
          : `R2/direct upload failed${hint}`;
      throw new Error(msg);
    }
    if (!uploadResp.ok) {
      throw new Error(
        `Object storage returned ${uploadResp.status} ${uploadResp.statusText}. ` +
          'Check bucket policy and that Content-Type matches the presigned signature.'
      );
    }
    const { data: reg } = await api.post<UploadResponse>('/datasets/register', {
      object_key: urlData.object_key,
      filename: file.name,
      file_size: file.size,
    });
    return { ...reg, dataset_id: reg.dataset_id, id: reg.dataset_id ?? reg.id, filename: file.name };
  },
  get: async (id: number): Promise<Dataset> => {
    const { data } = await api.get(`/datasets/${id}`);
    return data;
  },
};

export const analysisApi = {
  run: async (datasetId: number): Promise<Analysis> => {
    const { data } = await api.post(`/analysis/${datasetId}/analyze`);
    return { ...data, id: data.id ?? data.analysis_id };
  },
  runAsync: async (datasetId: number): Promise<Analysis> => {
    const { data } = await api.post(`/analysis/${datasetId}/analyze-async`);
    return { ...data, id: data.id ?? data.analysis_id };
  },
  getStatus: async (analysisId: number): Promise<AnalysisStatus> => {
    const { data } = await api.get(`/analysis/${analysisId}/status`);
    return data;
  },
  pollUntilComplete: async (
    analysisId: number,
    onTick?: (status: AnalysisStatus) => void,
    intervalMs = 2000,
    maxAttempts = 120
  ): Promise<AnalysisStatus> => {
    for (let i = 0; i < maxAttempts; i++) {
      const st = await analysisApi.getStatus(analysisId);
      onTick?.(st);
      if (st.status === 'complete' || st.status === 'failed') {
        return st;
      }
      await new Promise((r) => setTimeout(r, intervalMs));
    }
    throw new Error('Analysis timed out');
  },
  getResults: async (id: number): Promise<AnalysisResult> => {
    const { data } = await api.get(`/analysis/${id}/results`);
    return data;
  },
  submitDecisions: async (id: number, decisions: Record<string, 'keep' | 'delete' | 'normalize'>) => {
    const { data } = await api.post(`/analysis/${id}/decisions`, { decisions });
    return data;
  },
  applyDecisions: async (id: number) => {
    const { data } = await api.post(`/analysis/${id}/apply`);
    return data;
  },
  getSummary: async (id: number): Promise<AnalysisSummaryPayload> => {
    const { data } = await api.get(`/analysis/${id}/summary`);
    return data;
  },
  getDomains: async (id: number): Promise<DomainsPayload> => {
    const { data } = await api.get(`/analysis/${id}/domains`);
    return data;
  },
  getClusters: async (id: number): Promise<ClustersPayload> => {
    const { data } = await api.get(`/analysis/${id}/clusters`);
    return data;
  },
  getGraph: async (id: number): Promise<GraphPayload> => {
    const { data } = await api.get(`/analysis/${id}/graph`);
    return data;
  },
  getKnowledgeGraph: async (id: number): Promise<{ meta: Record<string, unknown>; knowledge_graph: Record<string, unknown> }> => {
    const { data } = await api.get(`/analysis/${id}/knowledge-graph`);
    return data;
  },
};

export const reportsApi = {
  download: async (id: number): Promise<Blob> => {
    const { data } = await api.get(`/reports/${id}/download`, {
      responseType: 'blob',
    });
    return data;
  },
};

// ---------------- Report Builder (6-phase architecture) ----------------

export interface ReportTemplate {
  id: number;
  name: string;
  description?: string | null;
  page_count?: number | null;
  extraction_method?: string | null;
  block_count: number;
  source_hash?: string | null;
  created_at?: string | null;
}

export interface ReportTemplateWithAst extends ReportTemplate {
  ast: Record<string, unknown>;
}

export interface ReportJob {
  id: number;
  analysis_id: number;
  template_id?: number | null;
  status: string;
  stage?: string | null;
  content_hash?: string | null;
  final_pdf_path?: string | null;
  kg_export_path?: string | null;
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface VerifierCheck {
  claim: string;
  claimed_value: number;
  computed_value?: number | null;
  tolerance: number;
  status: 'pass' | 'fail' | 'unverified';
  note: string;
}

export interface VerifierVerdict {
  block_id: string;
  overall_status: 'pass' | 'warn' | 'fail';
  checks: VerifierCheck[];
}

export interface RenderedBlock {
  block_id: string;
  kind: 'narrative' | 'table' | 'chart' | 'metric' | 'heading' | 'list';
  title: string;
  section: string;
  payload: Record<string, unknown>;
  verifier?: VerifierVerdict | null;
  route?: { engine: string; rationale: string } | null;
  version: number;
  generated_at: string;
}

export interface BlockCanvas {
  job_id: number;
  analysis_id: number;
  template_name: string;
  summary: Record<string, unknown>;
  sections: Array<{ section: string; blocks: RenderedBlock[] }>;
}

export interface JobCanvasResponse extends ReportJob {
  canvas?: BlockCanvas | null;
  verifier_report?: { blocks: VerifierVerdict[] } | null;
}

export interface ChatTurn {
  role: 'user' | 'assistant';
  text: string;
  block?: RenderedBlock | null;
  route?: { engine: string; rationale: string } | null;
  verifier?: VerifierVerdict | null;
  created_at: string;
}

export const reportBuilderApi = {
  listTemplates: async (): Promise<ReportTemplate[]> => {
    const { data } = await api.get('/report-builder/templates');
    return data;
  },
  uploadTemplate: async (
    name: string,
    file: File,
    description?: string
  ): Promise<ReportTemplateWithAst> => {
    const form = new FormData();
    form.append('name', name);
    if (description) form.append('description', description);
    form.append('file', file);
    const { data } = await api.post('/report-builder/templates/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },
  getTemplate: async (id: number) => {
    const { data } = await api.get(`/report-builder/templates/${id}`);
    return data;
  },
  deleteTemplate: async (id: number) => {
    await api.delete(`/report-builder/templates/${id}`);
  },
  defaultPreview: async (): Promise<Record<string, unknown>> => {
    const { data } = await api.get('/report-builder/templates/default/preview');
    return data;
  },
  generate: async (analysisId: number, templateId?: number | null): Promise<ReportJob> => {
    const { data } = await api.post('/report-builder/generate', {
      analysis_id: analysisId,
      template_id: templateId ?? null,
    });
    return data;
  },
  listJobs: async (analysisId?: number): Promise<ReportJob[]> => {
    const params = analysisId ? { analysis_id: analysisId } : {};
    const { data } = await api.get('/report-builder/jobs', { params });
    return data;
  },
  getJob: async (jobId: number): Promise<ReportJob> => {
    const { data } = await api.get(`/report-builder/jobs/${jobId}`);
    return data;
  },
  getCanvas: async (jobId: number): Promise<JobCanvasResponse> => {
    const { data } = await api.get(`/report-builder/jobs/${jobId}/canvas`);
    return data;
  },
  downloadPdf: async (jobId: number): Promise<Blob> => {
    const { data } = await api.get(`/report-builder/jobs/${jobId}/download`, {
      responseType: 'blob',
    });
    return data;
  },
  regenerateBlock: async (jobId: number, blockId: string): Promise<RenderedBlock> => {
    const { data } = await api.post(
      `/report-builder/jobs/${jobId}/blocks/${blockId}/regenerate`
    );
    return data;
  },
  recordCorrection: async (
    jobId: number,
    blockId: string,
    payload: { before?: string; after: string; kind?: string }
  ) => {
    const { data } = await api.post(
      `/report-builder/jobs/${jobId}/blocks/${blockId}/correction`,
      { ...payload, kind: payload.kind || 'narrative_edit' }
    );
    return data;
  },
  chat: async (jobId: number, query: string): Promise<ChatTurn> => {
    const { data } = await api.post(`/report-builder/jobs/${jobId}/chat`, { query });
    return data;
  },
  chatHistory: async (jobId: number): Promise<{ turns: ChatTurn[] }> => {
    const { data } = await api.get(`/report-builder/jobs/${jobId}/chat/history`);
    return data;
  },
  insertBlock: async (
    jobId: number,
    payload: { section: string; block: Record<string, unknown>; position?: number | null }
  ): Promise<RenderedBlock> => {
    const { data } = await api.post(
      `/report-builder/jobs/${jobId}/blocks/insert`,
      payload
    );
    return data;
  },
  moveBlock: async (
    jobId: number,
    payload: { block_id: string; target_section: string; target_position?: number | null }
  ) => {
    const { data } = await api.post(`/report-builder/jobs/${jobId}/blocks/move`, payload);
    return data;
  },
  deleteBlock: async (jobId: number, blockId: string) => {
    const { data } = await api.delete(`/report-builder/jobs/${jobId}/blocks/${blockId}`);
    return data;
  },
  reExport: async (jobId: number) => {
    const { data } = await api.post(`/report-builder/jobs/${jobId}/re-export`);
    return data;
  },
  pollJobUntilDone: async (
    jobId: number,
    onTick?: (j: ReportJob) => void,
    intervalMs = 2000,
    maxAttempts = 180
  ): Promise<ReportJob> => {
    for (let i = 0; i < maxAttempts; i++) {
      const j = await reportBuilderApi.getJob(jobId);
      onTick?.(j);
      if (j.status === 'exported' || j.status === 'failed' || j.status === 'verified') {
        return j;
      }
      await new Promise((r) => setTimeout(r, intervalMs));
    }
    throw new Error('Report builder job timed out');
  },
};

export default api;
