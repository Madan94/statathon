'use client';

import ImputationReviewTable from '@/components/analysis/ImputationReviewTable';
import type { AnalysisResult } from '@/lib/api';

interface Props {
  column: string;
  analysisId: number;
  results: AnalysisResult;
  className?: string;
  onSaved?: () => void;
}

/** Missing value review — delegates to ImputationReviewTable. */
export default function MissingPanel(props: Props) {
  return <ImputationReviewTable {...props} />;
}
