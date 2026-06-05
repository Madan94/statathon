'use client';

import { useState } from 'react';
import { Card } from '@/components/ui/Card';
import { Alert } from '@/components/ui/Alert';
import type { EnterpriseDocumentAST } from '@/lib/enterpriseAstTypes';

const TABS = [
  'Metadata',
  'Layout',
  'Content',
  'Tables',
  'Figures',
  'Semantic',
  'Graphs',
  'Retrieval',
  'Quality',
] as const;

type Tab = (typeof TABS)[number];

function countNodes(ast: Record<string, unknown>): number {
  const sem = ast.semanticAST as { nodes?: unknown[] } | undefined;
  return Array.isArray(sem?.nodes) ? sem.nodes.length : 0;
}

export default function EnterpriseAstPreview({ ast }: { ast: Record<string, unknown> }) {
  const [tab, setTab] = useState<Tab>('Metadata');
  const meta = (ast.metadata as Record<string, unknown>) || {};
  const quality = (ast.quality_report as Record<string, unknown>) || {};
  const isV2 = meta.version === '2.0' || 'layoutAST' in ast;

  if (!isV2) {
    return (
      <Alert variant="warning">
        Template is legacy v1 format. Re-extract PDF or re-import to upgrade to enterprise AST v2.0.
      </Alert>
    );
  }

  const renderBody = () => {
    switch (tab) {
      case 'Metadata':
        return (
          <pre className="text-xs overflow-auto max-h-96 p-3 bg-surface rounded border border-border">
            {JSON.stringify(meta, null, 2)}
          </pre>
        );
      case 'Layout':
        return (
          <pre className="text-xs overflow-auto max-h-96 p-3 bg-surface rounded border border-border">
            {JSON.stringify(ast.layoutAST, null, 2)}
          </pre>
        );
      case 'Content':
        return (
          <pre className="text-xs overflow-auto max-h-96 p-3 bg-surface rounded border border-border">
            {JSON.stringify(ast.contentAST, null, 2)}
          </pre>
        );
      case 'Tables':
        return (
          <pre className="text-xs overflow-auto max-h-96 p-3 bg-surface rounded border border-border">
            {JSON.stringify(ast.tableAST, null, 2)}
          </pre>
        );
      case 'Figures':
        return (
          <pre className="text-xs overflow-auto max-h-96 p-3 bg-surface rounded border border-border">
            {JSON.stringify(ast.figureAST, null, 2)}
          </pre>
        );
      case 'Semantic':
        return (
          <pre className="text-xs overflow-auto max-h-96 p-3 bg-surface rounded border border-border">
            {JSON.stringify(ast.semanticAST, null, 2)}
          </pre>
        );
      case 'Graphs':
        return (
          <pre className="text-xs overflow-auto max-h-96 p-3 bg-surface rounded border border-border">
            {JSON.stringify(
              {
                entityGraph: ast.entityGraph,
                relationshipGraph: ast.relationshipGraph,
                knowledgeGraph: ast.knowledgeGraph,
                factGraph: ast.factGraph,
                analyticsAST: ast.analyticsAST,
                citationAST: ast.citationAST,
              },
              null,
              2,
            )}
          </pre>
        );
      case 'Retrieval':
        return (
          <pre className="text-xs overflow-auto max-h-96 p-3 bg-surface rounded border border-border">
            {JSON.stringify(ast.retrievalAST, null, 2)}
          </pre>
        );
      case 'Quality':
        return (
          <div className="space-y-2">
            <p className="text-sm">
              Score: <strong>{String(quality.score ?? '—')}</strong> · Passed:{' '}
              <strong>{quality.passed ? 'yes' : 'no'}</strong>
            </p>
            {Array.isArray(quality.errors) && quality.errors.length > 0 && (
              <Alert variant="error">{quality.errors.join('; ')}</Alert>
            )}
            {Array.isArray(quality.warnings) && (quality.warnings as string[]).slice(0, 8).map((w) => (
              <p key={w} className="text-xs text-text-muted">
                {w}
              </p>
            ))}
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <Card className="p-3">
          <p className="text-[11px] text-text-muted">Document ID</p>
          <p className="text-sm font-mono truncate">{String(meta.documentId || '—')}</p>
        </Card>
        <Card className="p-3">
          <p className="text-[11px] text-text-muted">Pages</p>
          <p className="text-sm font-medium">{String(meta.page_count ?? ast.page_count ?? 0)}</p>
        </Card>
        <Card className="p-3">
          <p className="text-[11px] text-text-muted">Semantic nodes</p>
          <p className="text-sm font-medium">{countNodes(ast)}</p>
        </Card>
        <Card className="p-3">
          <p className="text-[11px] text-text-muted">Checksum</p>
          <p className="text-xs font-mono truncate">{String(meta.checksum || '—').slice(0, 16)}…</p>
        </Card>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-border pb-2">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`px-2 py-1 text-xs rounded ${
              tab === t ? 'bg-primary text-white' : 'text-text-muted hover:bg-border/40'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {renderBody()}
    </div>
  );
}
