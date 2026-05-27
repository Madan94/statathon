'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { reportsApi, analysisApi } from '@/lib/api';
import ReportPreview from '@/components/ReportPreview';
import PageHeader from '@/components/layout/PageHeader';
import WorkflowStepper from '@/components/layout/WorkflowStepper';
import Card from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { SkeletonCard } from '@/components/ui/Skeleton';
import { Alert } from '@/components/ui/Alert';
import { Download, FileText, Hash } from 'lucide-react';

export default function ReportPage() {
  const params = useParams();
  const id = Number(params.id);
  const [reportUrl, setReportUrl] = useState<string | null>(null);
  const [contentHash, setContentHash] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let revoked = false;
    Promise.all([
      reportsApi.download(id),
      analysisApi.getResults(id).catch(() => null),
    ])
      .then(([blob, results]) => {
        if (revoked) return;
        const url = URL.createObjectURL(blob);
        setReportUrl(url);
        if (results?.content_hash) setContentHash(results.content_hash);
      })
      .catch(() => setError('Report not found or API unavailable'))
      .finally(() => setLoading(false));

    return () => {
      revoked = true;
    };
  }, [id]);

  useEffect(() => {
    return () => {
      if (reportUrl) URL.revokeObjectURL(reportUrl);
    };
  }, [reportUrl]);

  const handleDownload = () => {
    if (reportUrl) {
      const a = document.createElement('a');
      a.href = reportUrl;
      a.download = `bharatstat-report-${id}.pdf`;
      a.click();
    }
  };

  if (loading) {
    return (
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <SkeletonCard />
        </div>
        <SkeletonCard />
      </div>
    );
  }

  if (!reportUrl) {
    return (
      <Alert variant="error" title="Report unavailable">
        {error || 'Could not load the PDF report.'}
      </Alert>
    );
  }

  return (
    <div>
      <WorkflowStepper currentStep={4} className="mb-8" />
      <PageHeader
        title="Audit report"
        description="Tamper-proof PDF with content hash for verification."
        actions={
          <Link href={`/analysis/${id}`}>
            <Button variant="outline" size="sm">
              Back to analysis
            </Button>
          </Link>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <ReportPreview reportUrl={reportUrl} onDownload={handleDownload} />
        </div>
        <aside className="space-y-4" aria-label="Report metadata">
          <Card>
            <div className="flex items-center gap-2 text-text mb-4">
              <FileText className="h-5 w-5 text-accent" aria-hidden />
              <h2 className="font-semibold">Report details</h2>
            </div>
            <dl className="space-y-4 text-sm">
              <div>
                <dt className="text-text-muted">Analysis ID</dt>
                <dd className="font-mono text-text mt-0.5">{id}</dd>
              </div>
              {contentHash && (
                <div>
                  <dt className="text-text-muted flex items-center gap-1">
                    <Hash className="h-3.5 w-3.5" aria-hidden />
                    Content hash
                  </dt>
                  <dd className="font-mono text-xs text-text break-all mt-1">{contentHash}</dd>
                </div>
              )}
            </dl>
            <Button className="w-full mt-6" onClick={handleDownload}>
              <Download className="h-4 w-4" aria-hidden />
              Download PDF
            </Button>
          </Card>
          <p className="text-xs text-text-muted">
            BharatStat reports are generated server-side and hashed for audit trails. Verify the
            hash matches your analysis results before publication.
          </p>
        </aside>
      </div>
    </div>
  );
}
