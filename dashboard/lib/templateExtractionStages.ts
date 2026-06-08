import type { TemplateExtractionJob } from '@/lib/api';

export interface TemplateExtractionStageDef {
  id: string;
  shortLabel: string;
  label: string;
  description: string;
  defaultTools: string[];
}

/** Queued + 6 production stages (matches report_builder/blueprint.py PRODUCTION_STAGE_ORDER). */
export const TEMPLATE_EXTRACTION_STAGES: TemplateExtractionStageDef[] = [
  {
    id: 'queued',
    shortLabel: 'Q',
    label: 'Queued',
    description: 'Job accepted and waiting for the extraction worker.',
    defaultTools: ['FastAPI', 'Background task'],
  },
  {
    id: 'stage1_immutable_ingestion_vaulting',
    shortLabel: 'Vault',
    label: 'Ingest & vault',
    description: 'Hashing the PDF and storing an immutable copy in the S3 vault.',
    defaultTools: ['SHA-256', 'S3 immutable vault'],
  },
  {
    id: 'stage2_vision_spatial_layout_parsing',
    shortLabel: 'Layout',
    label: 'Layout parsing',
    description: 'Extracting page layout, headings, tables, and spatial structure from the PDF.',
    defaultTools: ['ColPali', 'pdfplumber', 'PyMuPDF'],
  },
  {
    id: 'stage3_semantic_blueprint_extraction',
    shortLabel: 'Blueprint',
    label: 'Blueprint extract',
    description: 'Compiling semantic block specs and generalized questions from page summaries.',
    defaultTools: ['SGLang', 'Gemini', 'Heuristics'],
  },
  {
    id: 'stage4_required_answer_structure_modeling',
    shortLabel: 'Schema',
    label: 'Answer schema',
    description: 'Modeling datagrid, narrative, and chart answer structures for each block.',
    defaultTools: ['Datagrid schema', 'Narrative schema', 'Chart schema'],
  },
  {
    id: 'stage5_detailed_ast_hierarchy_assembly',
    shortLabel: 'Hierarchy',
    label: 'AST hierarchy',
    description: 'Assembling topics, subtopics, and block hierarchy for the template skeleton.',
    defaultTools: ['Topic assembly', 'BlockSpec builder'],
  },
  {
    id: 'stage6_final_ast_json_layout',
    shortLabel: 'AST',
    label: 'Final AST JSON',
    description: 'Serializing the production blueprint payload and persisting to Postgres.',
    defaultTools: ['TemplateAST', 'Postgres report_templates'],
  },
];

export function stageIndexById(stageId: string | null | undefined): number {
  if (!stageId) return 0;
  const idx = TEMPLATE_EXTRACTION_STAGES.findIndex((s) => s.id === stageId);
  return idx >= 0 ? idx : 0;
}

function highestCompletedStageIndex(
  diagnostics: Record<string, unknown> | null | undefined
): number {
  if (!diagnostics || typeof diagnostics !== 'object') return 0;
  let max = 0;
  for (const key of Object.keys(diagnostics)) {
    const idx = stageIndexById(key);
    const entry = diagnostics[key];
    if (
      idx > max &&
      entry &&
      typeof entry === 'object' &&
      (entry as { status?: string }).status === 'completed'
    ) {
      max = idx;
    }
  }
  return max;
}

export function resolveActiveStageIndex(job: TemplateExtractionJob | null): number {
  if (!job) return 0;
  if (job.status === 'pending') return 0;
  if (job.status === 'completed') return TEMPLATE_EXTRACTION_STAGES.length - 1;
  const fromStage = stageIndexById(job.stage);
  const fromDiagnostics = highestCompletedStageIndex(
    job.stage_diagnostics as Record<string, unknown> | null | undefined
  );
  if (job.status === 'failed') {
    return Math.max(fromStage, fromDiagnostics);
  }
  return Math.max(fromStage, fromDiagnostics);
}

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === 'object' && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

export function buildStageLiveMessage(
  stageId: string,
  diagnostics: Record<string, unknown> | null | undefined
): string {
  const entry = asRecord(diagnostics?.[stageId]);
  if (!entry) {
    return stageId === 'queued' ? 'Waiting for worker…' : 'Running…';
  }

  const parts: string[] = [];
  const status = entry.status;
  if (status === 'started') parts.push('In progress…');
  if (status === 'completed') parts.push('Completed');

  if (typeof entry.page_count === 'number') {
    parts.push(`${entry.page_count} page(s) parsed`);
  }
  if (typeof entry.extraction_method === 'string' && entry.extraction_method) {
    parts.push(`Method: ${entry.extraction_method}`);
  }
  if (typeof entry.sha256 === 'string' && entry.sha256) {
    parts.push(`SHA256: ${entry.sha256.slice(0, 16)}…`);
  }
  if (typeof entry.questions_count === 'number') {
    parts.push(`${entry.questions_count} question(s)`);
  }
  if (typeof entry.block_count === 'number') {
    parts.push(`${entry.block_count} block(s)`);
  }
  if (entry.vault_object_key) {
    parts.push('Vault upload recorded');
  }
  if (typeof entry.file_size_kb === 'number') {
    parts.push(`${entry.file_size_kb} KB source file`);
  }

  return parts.length > 0 ? parts.join(' · ') : 'Running…';
}

export function resolveStageTools(
  stageDef: TemplateExtractionStageDef,
  stageId: string,
  diagnostics: Record<string, unknown> | null | undefined
): string[] {
  const entry = asRecord(diagnostics?.[stageId]);
  const fromApi = entry?.tools;
  if (Array.isArray(fromApi) && fromApi.every((t) => typeof t === 'string')) {
    return fromApi as string[];
  }

  if (stageId === 'stage2_vision_spatial_layout_parsing') {
    const method = String(entry?.extraction_method || '').toLowerCase();
    if (method.includes('colpali')) return ['ColPali', 'Vision sidecar'];
    if (method.includes('pdfplumber')) return ['pdfplumber', 'PyMuPDF'];
    if (method.includes('pymupdf')) return ['PyMuPDF'];
    if (method.includes('layoutlm')) return ['LayoutLM', 'Qwen-VL'];
  }

  if (stageId === 'stage3_semantic_blueprint_extraction') {
    const method = String(
      (diagnostics?.['stage2_vision_spatial_layout_parsing'] as Record<string, unknown>)
        ?.extraction_method || ''
    ).toLowerCase();
    if (method.includes('sequential') || method.includes('sglang')) {
      return ['SGLang', 'Qwen2.5-3B'];
    }
  }

  return stageDef.defaultTools;
}

export function getStageDef(stageId: string): TemplateExtractionStageDef {
  return (
    TEMPLATE_EXTRACTION_STAGES.find((s) => s.id === stageId) ??
    TEMPLATE_EXTRACTION_STAGES[0]
  );
}

export function activeStageId(job: TemplateExtractionJob | null): string {
  if (!job) return 'queued';
  if (job.status === 'pending') return 'queued';
  return job.stage || 'queued';
}
