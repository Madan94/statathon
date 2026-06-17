import type { GeneratedSectionBlock, ReportSectionRequest } from '@/lib/report-section';

export interface AcceptedPreviewMetadata {
  acceptedAt: string;
  acceptanceKey: string;
  previewMode: 'frontend_rows' | 'schema_only';
  rowCounts: {
    rowsScanned?: number;
    rowsAfterFilter?: number;
    rowsVisible: number;
    rowsRendered: number;
    cachedRowsAvailable: boolean;
  };
  filters: Array<{ col: string; op: string; value?: unknown; connector?: 'AND' | 'OR' }>;
  weightPolicy: {
    scale: number;
    multiplierColumn?: string | null;
    formula: 'nss_multiplier_100';
  };
  measures: Array<{
    col: string;
    label: string;
    agg: string;
    weighted: boolean;
    weightCol?: string | null;
  }>;
  warnings: string[];
}

export interface ReportCanvasHandoffSection {
  id: string;
  request: ReportSectionRequest;
  blocks: GeneratedSectionBlock[];
  meta?: {
    rowsAfterFilter?: number;
    rowsScanned?: number;
    groups?: number;
    acceptedPreview?: AcceptedPreviewMetadata;
  };
  addedAt?: number;
}

export interface ReportCanvasHandoffBundle {
  version: 'report.canvas.handoff.v1';
  templateId: string;
  signature: string;
  datasetId: string;
  generatedAt: string;
  sections: ReportCanvasHandoffSection[];
}

export function canvasHandoffStorageKey(templateId: string, signature: string): string {
  return `report-canvas-handoff:${templateId}:${signature}`;
}