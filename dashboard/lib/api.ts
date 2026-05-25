import axios from 'axios';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const AUTH_TOKEN_KEY = 'bharatstat_token';
const LEGACY_TOKEN_KEY = 'statathon_token';

function persistToken(token: string) {
  if (typeof window === 'undefined') return;
  localStorage.setItem(AUTH_TOKEN_KEY, token);
  localStorage.removeItem(LEGACY_TOKEN_KEY);
}

function clearToken() {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(LEGACY_TOKEN_KEY);
}

function readToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(AUTH_TOKEN_KEY) || localStorage.getItem(LEGACY_TOKEN_KEY);
}

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const setAuthToken = (token: string | null) => {
  if (token) {
    api.defaults.headers.common['Authorization'] = `Bearer ${token}`;
  } else {
    delete api.defaults.headers.common['Authorization'];
  }
};

export const storeAuthToken = (token: string) => {
  setAuthToken(token);
  persistToken(token);
};

export interface UploadResponse {
  dataset_id: number;
  id: number;
  filename: string;
}

export interface PresignedUploadResponse {
  upload_url: string;
  object_key: string;
  expires_in: number;
}

export interface Dataset {
  id: number;
  filename: string;
  row_count: number;
  column_count: number;
  status: string;
  created_at: string;
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
  [key: string]: unknown;
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

export interface AnalysisResult {
  analysis_id?: number;
  health?: Record<string, unknown>;
  schema?: Record<string, string>;
  semantic?: Record<string, string>;
  semantic_mapping?: SemanticMappingRow[];
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

export const authApi = {
  register: async (email: string, password: string) => {
    const { data } = await api.post('/auth/register', { email, password });
    return data;
  },
  login: async (email: string, password: string) => {
    const { data } = await api.post('/auth/login', { email, password });
    if (data.access_token) {
      setAuthToken(data.access_token);
      persistToken(data.access_token);
    }
    return data;
  },
  googleAuthUrl: async (): Promise<{ url: string }> => {
    const { data } = await api.get('/auth/oauth/google/url');
    return data;
  },
  logout: () => {
    setAuthToken(null);
    clearToken();
  },
  restoreToken: () => {
    if (typeof window === 'undefined') return;
    const token = readToken();
    if (token) {
      setAuthToken(token);
      if (localStorage.getItem(LEGACY_TOKEN_KEY)) {
        persistToken(token);
      }
    }
  },
};

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
    const ext = file.name.split('.').pop()?.toLowerCase();
    const contentType =
      ext === 'csv'
        ? 'text/csv'
        : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
    const { data: urlData } = await api.post<PresignedUploadResponse>('/datasets/upload-url', {
      filename: file.name,
      content_type: contentType,
    });
    await fetch(urlData.upload_url, {
      method: 'PUT',
      body: file,
      headers: { 'Content-Type': contentType },
    });
    const { data: reg } = await api.post('/datasets/register', {
      object_key: urlData.object_key,
      filename: file.name,
      file_size: file.size,
    });
    return { dataset_id: reg.dataset_id, id: reg.dataset_id, filename: file.name };
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
