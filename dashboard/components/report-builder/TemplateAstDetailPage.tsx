'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowLeft, Loader2 } from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import TemplateExtractionPreview from '@/components/report-builder/TemplateExtractionPreview';
import { reportBuilderApi, ReportTemplateWithAst } from '@/lib/api';
import { resolveTemplateBySlug } from '@/lib/templateRouteUtils';

const AST_GENERATOR_BASE = '/report/report-ast-generator';

export default function TemplateAstDetailPage({ templateSlug }: { templateSlug: string }) {
  const router = useRouter();
  const [template, setTemplate] = useState<ReportTemplateWithAst | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      setTemplate(null);
      try {
        const templates = await reportBuilderApi.listTemplates();
        const matched = resolveTemplateBySlug(templates, templateSlug);
        if (!matched) {
          if (!cancelled) {
            setError('Template not found.');
            setLoading(false);
          }
          return;
        }
        const full = await reportBuilderApi.getTemplate(matched.id);
        if (!cancelled) {
          setTemplate(full);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load template AST');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [templateSlug]);

  const ast =
    template?.ast && typeof template.ast === 'object' ? template.ast : null;

  return (
    <>
      <div className="mb-4">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.push(AST_GENERATOR_BASE)}
          className="gap-1.5 -ml-2 text-text-muted hover:text-text"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          Back to Report AST Generator
        </Button>
      </div>

      <PageHeader
        title={template?.name ?? 'Template blueprint'}
        description={
          template
            ? `Template #${template.id} — structure, entities, tables, charts and question blueprint from stored AST.`
            : 'Loading extracted template AST…'
        }
      />

      {error && <Alert variant="error">{error}</Alert>}

      {error && !loading && (
        <div className="mt-4">
          <Link href={AST_GENERATOR_BASE}>
            <Button variant="outline" size="sm">
              Return to templates
            </Button>
          </Link>
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 py-12 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading template AST…
        </div>
      )}

      {!loading && ast && (
        <Card
          title="Extracted PDF layout and blueprint"
          description={`${template!.name} (template #${template!.id})`}
        >
          <TemplateExtractionPreview ast={ast} />
        </Card>
      )}

      {!loading && template && !ast && !error && (
        <Alert variant="warning">
          No AST data stored for this template. Re-run extraction from the AST generator page.
        </Alert>
      )}
    </>
  );
}
