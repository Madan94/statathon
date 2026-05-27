'use client';



import Card from '@/components/ui/Card';

import { Badge } from '@/components/ui/Badge';



interface Stage {

  id: string;

  label: string;

  status: 'done' | 'pending' | 'warn';

  detail?: string;

}



interface PipelineStageSummaryProps {

  auditLogs?: Array<Record<string, unknown>>;

  phase3?: Record<string, unknown>;

}



function stageFromPhase3(phase3: Record<string, unknown> | undefined): Stage[] {

  const p3 = phase3 || {};

  const valCount = Array.isArray(p3.validation_candidates) ? p3.validation_candidates.length : 0;

  const anomCount = Array.isArray(p3.anomaly_candidates) ? p3.anomaly_candidates.length : 0;

  const impCount = Array.isArray(p3.imputation_candidates) ? p3.imputation_candidates.length : 0;

  const decisions =

    p3.user_decisions && typeof p3.user_decisions === 'object'

      ? Object.keys(p3.user_decisions as object).length

      : 0;



  return [

    { id: 'ingest', label: 'Data ingestion', status: 'done', detail: 'Health + profiling' },

    { id: 'semantic', label: 'Semantic mapping', status: 'done', detail: 'Domains + graph' },

    {

      id: 'validation',

      label: 'Rule validation',

      status: valCount ? 'warn' : 'done',

      detail: `${valCount} candidates`,

    },

    {

      id: 'outliers',

      label: 'Outlier detection',

      status: anomCount ? 'warn' : 'done',

      detail: `${anomCount} flags`,

    },

    {

      id: 'imputation',

      label: 'Imputation scoring',

      status: impCount ? 'warn' : 'done',

      detail: `${impCount} columns`,

    },

    {

      id: 'decisions',

      label: 'User decisions',

      status: decisions ? 'done' : 'pending',

      detail: `${decisions} recorded`,

    },

    { id: 'report', label: 'Report generation', status: 'done', detail: 'PDF + SHA-256' },

  ];

}



const statusBadge = {

  done: 'success' as const,

  warn: 'warning' as const,

  pending: 'muted' as const,

};



export default function PipelineStageSummary({ auditLogs, phase3 }: PipelineStageSummaryProps) {

  const stages = stageFromPhase3(phase3);

  const auditCount = Array.isArray(auditLogs) ? auditLogs.length : 0;



  return (

    <Card title="Pipeline stages" description="End-to-end survey intelligence workflow">

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">

        {stages.map((s) => (

          <div

            key={s.id}

            className="p-3 rounded-lg border border-border bg-white"

          >

            <div className="flex items-start justify-between gap-2 mb-1">

              <p className="font-medium text-text text-sm">{s.label}</p>

              <Badge variant={statusBadge[s.status]} className="shrink-0 text-[10px]">

                {s.status === 'done' ? 'Done' : s.status === 'warn' ? 'Review' : 'Pending'}

              </Badge>

            </div>

            <p className="text-text-muted text-xs">{s.detail}</p>

          </div>

        ))}

      </div>

      {auditCount > 0 && (

        <p className="text-xs text-text-muted mt-4">{auditCount} semantic audit steps logged</p>

      )}

    </Card>

  );

}

