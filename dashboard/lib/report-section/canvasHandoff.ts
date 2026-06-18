import type { GeneratedSectionBlock, ReportSectionRequest } from '@/lib/report-section';

/**
 * Per-measure weighted vs unweighted aggregates computed from the accepted
 * filtered slice. Travels with the accepted preview into the description,
 * components and preview steps so the synthesizer can ground the report in the
 * exact figures the officer saw.
 */
export interface WeightMeasureInsight {
  col: string;
  label: string;
  aggregation: string;
  weighted: boolean;
  rowsUsed: number;
  rowsSkipped: number;
  weightSum: number | null;        // Σ(wᵢ/scale) over used rows
  weightedTotal: number | null;    // Σ(xᵢ·wᵢ/scale)
  weightedMean: number | null;     // weightedTotal / weightSum
  unweightedTotal: number | null;  // Σ xᵢ
  unweightedMean: number | null;   // Σ xᵢ / n
  selectedValue: number | null;    // value for the chosen aggregation
  delta: number | null;            // weightedMean − unweightedMean (when both exist)
}

export interface WeightInsights {
  version: 'weight.insights.v1';
  weightColumn: string | null;
  weightScale: number;
  weightingApplied: boolean;       // true when any measure is weighted
  rowsScanned?: number;
  rowsAfterFilter?: number;
  nonPositiveWeightRows: number;
  filters: Array<{ col: string; op: string; value?: unknown; connector?: 'AND' | 'OR' }>;
  measures: WeightMeasureInsight[];
  formula: {
    weightedValue: string;
    weightedTotal: string;
    weightedMean: string;
  };
  notes: string[];
}

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
  /** Structured weighted/unweighted insights JSON for the report synthesizer. */
  weightInsights?: WeightInsights;
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