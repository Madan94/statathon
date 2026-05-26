'use client';

import { useState } from 'react';
import type { AnalysisResult, ColumnProfile } from '@/lib/api';
import ColumnNav from './columns/ColumnNav';
import AnomalyPanel from './columns/AnomalyPanel';
import MissingPanel from './columns/MissingPanel';
import WorkflowStepper from '@/components/layout/WorkflowStepper';
import { Network, LayoutList } from 'lucide-react';

interface Props {
  results: AnalysisResult;
  onBack: () => void;
}

export default function ColumnAnalysisLayout({ results, onBack }: Props) {
  const [selectedColumn, setSelectedColumn] = useState<string | null>(null);

  const columnProfiles = results.column_profiles as Record<string, ColumnProfile> | undefined;
  const schema = results.schema ?? {};
  const allColumns = Object.keys(columnProfiles ?? schema);

  return (
    <div className="flex flex-col" style={{ minHeight: 'calc(100vh - 160px)' }}>
      <WorkflowStepper currentStep={3} className="mb-4" />

      <div className="flex flex-1 overflow-hidden rounded-xl border border-border">
        {/* Left nav */}
        <ColumnNav
          results={results}
          selectedColumn={selectedColumn}
          onSelectColumn={setSelectedColumn}
          onBack={onBack}
        />

        {/* Right panel */}
        <main className="flex-1 overflow-y-auto p-6">
          {selectedColumn ? (
            <div className="space-y-6 max-w-4xl">
              <div className="flex items-center gap-3 pb-4 border-b border-border">
                <div className="h-8 w-8 rounded-lg bg-accent/10 flex items-center justify-center">
                  <Network className="h-4 w-4 text-primary" />
                </div>
                <div>
                  <h2 className="text-xl font-bold text-text font-mono">{selectedColumn}</h2>
                  <p className="text-xs text-text-muted mt-0.5">
                    {results.schema?.[selectedColumn] ??
                      (columnProfiles?.[selectedColumn] as ColumnProfile | undefined)?.datatype ??
                      'unknown type'}{' '}
                    ·{' '}
                    {results.semantic_mapping?.find((r) => r.column === selectedColumn)?.domain ??
                      'no domain'}
                  </p>
                </div>
              </div>

              <AnomalyPanel column={selectedColumn} results={results} />
              <MissingPanel column={selectedColumn} results={results} />
            </div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center py-24 text-center">
              <LayoutList className="h-12 w-12 text-text-muted mb-4" aria-hidden />
              <p className="font-semibold text-text text-lg">Select a column</p>
              <p className="mt-2 text-sm text-text-muted max-w-md">
                {allColumns.length} columns available. Click any column in the left panel to
                analyse its anomalies and missing values.
              </p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
