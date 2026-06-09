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
  dev_otp?: string | null;
}

/** Extract a readable message from axios / fetch errors. */
export function formatApiError(err: unknown, fallback = 'Request failed'): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      return detail.map((d) => (typeof d === 'object' && d && 'msg' in d ? String(d.msg) : String(d))).join('; ');
    }
    if (detail && typeof detail === 'object') return JSON.stringify(detail);
    return err.message || fallback;
  }
  if (err instanceof Error) return err.message || fallback;
  return fallback;
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
  method_used?: string;
  metric?: number | null;
  z_abs?: number | null;
  iqr_excess?: number | null;
  lower_fence?: number | null;
  upper_fence?: number | null;
  reason?: string;
  isolation_forest?: boolean;
}

export type OutlierRowDecision =
  | 'KEEP'
  | 'NORMALIZE'
  | 'DELETE_VALUE'
  | 'DELETE_ROW'
  | 'EDIT_VALUE';

export interface GoodnessOfFitResult {
  column: string;
  mean?: number;
  median?: number;
  standard_deviation?: number;
  skewness?: number;
  kurtosis?: number;
  shapiro_w_statistic?: number | null;
  p_value?: number | null;
}

export interface AnomalyColumnBlock {
  column: string;
  recommended?: string;
  z_score_confidence?: number;
  iqr_confidence?: number;
  reason?: string[];
  method_selected?: string | null;
  detection_run?: boolean;
  goodness_of_fit?: GoodnessOfFitResult;
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

export interface DatasetProfile {
  dataset_id: number;
  row_count: number;
  column_count: number;
  file_size_mb?: number | null;
  memory_usage_mb?: number | null;
  numeric_columns: number;
  categorical_columns: number;
  missing_cells: number;
  duplicate_rows: number;
  completeness_score?: number | null;
  consistency_score?: number | null;
  health_score?: number | null;
  profile_version?: number;
  column_list?: string[];
  preview_rows?: Record<string, unknown>[];
  dtypes?: Record<string, string>;
  missing_per_column?: Record<string, number>;
  created_at?: string | null;
  updated_at?: string | null;
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
  file_size?: number | null;
  file_size_bytes?: number;
  file_size_mb?: number;
  storage_path?: string | null;
  object_key?: string | null;
  storage_provider?: string | null;
  upload_status?: string | null;
  checksum?: string | null;
  health_summary?: DatasetHealthSummary | Record<string, unknown> | null;
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
  value?: string | number | null;
  rule_id?: string;
  /** Rule id string or legacy nested rule object */
  rule?: string | { rule_id?: string; rule_expression?: string };
  reason?: string;
  expected?: string;
  explanation?: string;
  domain?: string;
  confidence?: number;
  confidence_band?: string;
  rule_source?: string;
  kg_relationships?: unknown;
  rule_params?: Record<string, unknown>;
}

export interface ValidationDecisionItem {
  rule_id?: string;
  column: string;
  row_index?: number | null;
  rule_type?: string;
  severity?: string;
  confidence?: number;
  decision: string;
  old_value?: string | number | null;
  new_value?: string | number | null;
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
  knowledge_graph?: Record<string, unknown>;
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
  effective_schema?: string[];
  normalization_version?: number | null;
}

export interface NormalizationColumnRecord {
  column_id?: number;
  original_name: string;
  normalized_name: string;
  is_deleted: boolean;
  is_excluded: boolean;
  is_active?: boolean;
}

export interface NormalizationSaveResponse {
  analysis_id: number;
  dataset_id: number;
  normalization_version: number;
  effective_schema: string[];
  column_count: number;
}

export interface EffectiveSchemaResponse {
  dataset_id: number;
  analysis_id: number;
  normalization_version: number | null;
  columns: string[];
  column_map: NormalizationColumnRecord[];
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

export interface ActivityItem {
  event_type: string;
  title: string;
  actor_id: number;
  created_at: string | null;
  metadata: Record<string, unknown>;
}

export const dashboardApi = {
  getSummary: async (): Promise<DashboardSummary> => {
    const { data } = await api.get('/dashboard/summary');
    return data;
  },
  getActivity: async (limit = 150): Promise<ActivityItem[]> => {
    const { data } = await api.get('/dashboard/activity', { params: { limit } });
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
  /** Development only — sign in as test officer without OTP. */
  devQuickLogin: async (email: string, password: string) => {
    const { data } = await api.post('/auth/dev/quick-login', { email, password });
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
  getProfile: async (id: number): Promise<DatasetProfile> => {
    const { data } = await api.get(`/datasets/${id}/profile`);
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
    intervalMs = 3000,
    maxAttempts = 400
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
  getResults: async (id: number, options?: { includePhase3?: boolean }): Promise<AnalysisResult> => {
    const { data } = await api.get(`/analysis/${id}/results`, {
      params: { include_phase3: options?.includePhase3 ?? false },
    });
    return data;
  },
  getNormalization: async (id: number): Promise<{ normalization_version: number | null; columns: NormalizationColumnRecord[] }> => {
    const { data } = await api.get(`/analysis/${id}/normalization`);
    return data;
  },
  saveNormalization: async (
    id: number,
    columns: Array<{
      original_name: string;
      normalized_name: string;
      is_deleted: boolean;
      is_excluded: boolean;
    }>
  ): Promise<NormalizationSaveResponse> => {
    const { data } = await api.post(`/analysis/${id}/normalization`, { columns });
    return data;
  },
  getEffectiveSchema: async (datasetId: number, analysisId: number): Promise<EffectiveSchemaResponse> => {
    const { data } = await api.get(`/datasets/${datasetId}/effective-schema`, {
      params: { analysis_id: analysisId },
    });
    return data;
  },
  submitDecisions: async (id: number, decisions: Record<string, 'keep' | 'delete' | 'normalize'>) => {
    const { data } = await api.post(`/analysis/${id}/decisions`, { decisions });
    return data;
  },
  selectOutlierMethod: async (id: number, column: string, method: 'Z_SCORE' | 'IQR') => {
    const { data } = await api.post(`/analysis/${id}/outliers/method`, { column, method });
    return data;
  },
  runOutlierDetection: async (id: number, column: string) => {
    const { data } = await api.post(`/analysis/${id}/outliers/detect`, { column });
    return data;
  },
  saveOutlierDecisions: async (
    id: number,
    column: string,
    decisions: Array<{
      row_index: number;
      method: string;
      severity: string;
      decision: OutlierRowDecision;
      old_value?: string | number | null;
      new_value?: string | number | null;
      confidence?: number;
      methodology?: string;
    }>,
  ) => {
    const { data } = await api.post(`/analysis/${id}/outliers/decisions`, { column, decisions });
    return data as { success?: boolean; saved: number; analysis_id: number; column: string };
  },
  getOutlierDecisions: async (id: number, column?: string) => {
    const { data } = await api.get(`/analysis/${id}/outliers/decisions`, {
      params: column ? { column } : undefined,
    });
    return data;
  },
  getAnomalyReviewProgress: async (id: number) => {
    const { data } = await api.get(`/analysis/${id}/anomaly/review-progress`);
    return data as {
      total_anomalies: number;
      reviewed: number;
      remaining: number;
      progress_pct: number;
      complete: boolean;
      columns_total?: number;
      columns_reviewed?: number;
      auto_reviewed?: number;
    };
  },
  getImputationReviewProgress: async (id: number) => {
    const { data } = await api.get(`/analysis/${id}/imputation/review-progress`);
    return data as {
      columns_with_missing: number;
      reviewed_columns: number;
      remaining_columns: number;
      progress_pct: number;
      complete: boolean;
      columns_total?: number;
      columns_reviewed?: number;
      auto_reviewed?: number;
    };
  },
  getPhaseStatus: async (id: number) => {
    const { data } = await api.get(`/analysis/${id}/phase-status`);
    return data as {
      analysis_id: number;
      rule_validation_completed: boolean;
      anomaly_completed: boolean;
      missing_value_completed: boolean;
      validation: {
        total: number;
        reviewed: number;
        complete: boolean;
        acknowledged: boolean;
      };
      anomaly: {
        columns_total: number;
        columns_reviewed: number;
        auto_reviewed: number;
        complete: boolean;
      };
      imputation: {
        columns_total: number;
        columns_reviewed: number;
        auto_reviewed: number;
        complete: boolean;
      };
      column_reviews?: {
        anomaly?: Array<{ column: string; status: string; item_count: number; reviewed_count: number }>;
        imputation?: Array<{ column: string; status: string; item_count: number; reviewed_count: number }>;
      };
    };
  },
  getValidationReviewProgress: async (id: number) => {
    const { data } = await api.get(`/analysis/${id}/validation/review-progress`);
    return data as {
      total: number;
      reviewed: number;
      remaining: number;
      progress_pct: number;
      complete: boolean;
      acknowledged: boolean;
    };
  },
  proceedValidation: async (
    id: number,
    decisions: ValidationDecisionItem[],
    meta: { critical_count?: number; candidate_count?: number },
  ) => {
    const { data } = await api.post(`/analysis/${id}/validation/proceed`, {
      decisions,
      ...meta,
    });
    return data as {
      success?: boolean;
      saved: number;
      rule_validation_completed: boolean;
    };
  },
  getImputationMissingRows: async (
    id: number,
    column: string,
    options?: { method?: string; offset?: number; limit?: number },
  ) => {
    const { data } = await api.get(`/analysis/${id}/imputation/missing-rows`, {
      params: { column, ...options },
    });
    return data as {
      total_missing: number;
      offset: number;
      limit: number;
      column: string;
      method: string;
      rows: Array<{
        row_index: number;
        missing_column: string;
        original_value: null;
        recommended_value: unknown;
        confidence: number;
        method: string;
        reason: string;
        context: Record<string, unknown>;
      }>;
    };
  },
  acknowledgeValidation: async (
    id: number,
    meta: { critical_count?: number; candidate_count?: number },
  ) => {
    const { data } = await api.post(`/analysis/${id}/validation/acknowledge`, meta);
    return data;
  },
  saveValidationDecisions: async (id: number, decisions: ValidationDecisionItem[]) => {
    const { data } = await api.post(`/analysis/${id}/validation/decisions`, { decisions });
    return data;
  },
  saveImputationDecisions: async (
    id: number,
    column: string,
    method: string,
    decisions?: Array<Record<string, unknown>>,
  ) => {
    const { data } = await api.post(`/analysis/${id}/imputation/decisions`, {
      column,
      method,
      decisions: decisions ?? [],
    });
    return data as { success?: boolean; saved: number; column: string; method: string };
  },
  applyLineage: async (id: number) => {
    const { data } = await api.post(`/analysis/${id}/apply`);
    return data;
  },
  getLineage: async (id: number) => {
    const { data } = await api.get(`/analysis/${id}/lineage`);
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

export interface TemplateExtractionJob {
  id: number;
  status: string;
  stage?: string | null;
  progress_pct: number;
  template_name: string;
  source_filename?: string | null;
  source_hash?: string | null;
  vault_object_key?: string | null;
  extraction_method?: string | null;
  stage_diagnostics?: Record<string, unknown> | null;
  error_message?: string | null;
  created_template_id?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface DataFilterSpec {
  include_columns?: string[] | null;
  exclude_columns?: string[] | null;
  max_rows?: number | null;
  min_complete_row_pct?: number | null;
}

export interface ReadyAnalysis {
  analysis_id: number;
  dataset_id: number;
  filename: string;
  row_count: number;
  column_count: number;
  status: string;
  upload_status?: string | null;
  created_at?: string | null;
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
  filter_config?: DataFilterSpec | null;
  delivery_log?: Array<Record<string, unknown>> | null;
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

export interface DeepAgentContext {
  dataset?: { loaded: boolean; rows: number; columns: number; col_sample: string[] };
  knowledge_graph?: { backend: string; available: boolean; note?: string };
  stm?: { backend: string; available: boolean };
  ltm?: { backend: string; available: boolean };
  rulebooks?: { available: boolean };
  analysis?: {
    semantic_mapped_columns: number;
    clusters: number;
    anomaly_candidates: number;
    imputation_candidates: number;
    has_schema_graph: boolean;
  };
  domains?: Record<string, number>;
}

export interface DeepAgentTurn {
  turn_id: string;
  query: string;
  role: 'user' | 'assistant';
  text: string;
  blocks: RenderedBlock[];
  plan?: { intent: string; target_domains: string[]; sub_intents: string[] };
  analytics?: { mode: string; error?: string; facts?: Record<string, unknown> };
  context_used?: {
    resolved_columns: string[];
    kg_neighbors_count: number;
    anomalies: number;
    imputations: number;
    intent: string;
  };
  verifier?: VerifierVerdict | null;
  error?: string | null;
  created_at: string;
}

export const reportBuilderApi = {
  listReadyAnalyses: async (): Promise<ReadyAnalysis[]> => {
    const { data } = await api.get('/report-builder/ready-analyses');
    return data;
  },
  cloneDefaultTemplate: async (): Promise<ReportTemplateWithAst> => {
    const { data } = await api.post('/report-builder/templates/clone-default');
    return data;
  },
  importJsonTemplate: async (
    name: string,
    ast: Record<string, unknown>,
    description?: string,
    documentFormat?: 'energy_chapter'
  ): Promise<ReportTemplateWithAst> => {
    const { data } = await api.post('/report-builder/templates/import-json', {
      name,
      description,
      ast,
      document_format: documentFormat,
    });
    return data;
  },
  updateTemplate: async (
    id: number,
    payload: {
      name?: string;
      description?: string;
      ast?: Record<string, unknown>;
      filter_config?: DataFilterSpec;
    }
  ): Promise<ReportTemplate> => {
    const { data } = await api.put(`/report-builder/templates/${id}`, payload);
    return data;
  },
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
  extractTemplateAsync: async (
    name: string,
    file: File,
    description?: string
  ): Promise<TemplateExtractionJob> => {
    const form = new FormData();
    form.append('name', name);
    if (description) form.append('description', description);
    form.append('file', file);
    const { data } = await api.post('/report-builder/templates/extract-async', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },
  getTemplateExtractJob: async (jobId: number): Promise<TemplateExtractionJob> => {
    const { data } = await api.get(`/report-builder/templates/extract-jobs/${jobId}`);
    return data;
  },
  pollTemplateExtractJob: async (
    jobId: number,
    onTick?: (job: TemplateExtractionJob) => void,
    intervalMs = 1500,
    maxAttempts = 240
  ): Promise<TemplateExtractionJob> => {
    for (let i = 0; i < maxAttempts; i++) {
      const job = await reportBuilderApi.getTemplateExtractJob(jobId);
      onTick?.(job);
      if (job.status === 'completed' || job.status === 'failed') {
        return job;
      }
      await new Promise((r) => setTimeout(r, intervalMs));
    }
    throw new Error('Template extraction timed out');
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
  generate: async (
    analysisId: number,
    templateId?: number | null,
    filterConfig?: DataFilterSpec | null
  ): Promise<ReportJob> => {
    const { data } = await api.post('/report-builder/generate', {
      analysis_id: analysisId,
      template_id: templateId ?? null,
      filter_config: filterConfig ?? null,
    });
    return data;
  },
  /** Coordinate-exact PDF from fina-ast layout + Deep BI (economics domain default). */
  coordGenerate: async (
    analysisId: number,
    options?: { astPath?: string; domain?: string; useGemini?: boolean }
  ): Promise<{ job_id: number; status: string; stage?: string; message: string }> => {
    const { data } = await api.post('/report-builder/coord-generate', {
      analysis_id: analysisId,
      ast_path: options?.astPath,
      domain: options?.domain ?? 'economics',
      use_gemini: options?.useGemini ?? true,
    });
    return data;
  },
  deliver: async (
    jobId: number,
    payload: { channel: 'email' | 'webhook'; to?: string; url?: string }
  ) => {
    const { data } = await api.post(`/report-builder/jobs/${jobId}/deliver`, payload);
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
  deepChat: async (jobId: number, query: string): Promise<DeepAgentTurn> => {
    const { data } = await api.post(`/report-builder/jobs/${jobId}/deep-chat`, { query });
    return data;
  },
  getJobContext: async (jobId: number): Promise<DeepAgentContext> => {
    const { data } = await api.get(`/report-builder/jobs/${jobId}/context`);
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
