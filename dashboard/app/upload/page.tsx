'use client';

import { useState, useCallback, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { datasetsApi, formatApiError, reportBuilderApi, ReadyAnalysis } from '@/lib/api';
import { toast } from '@/lib/toast';
import PageHeader from '@/components/layout/PageHeader';
import WorkflowStepper from '@/components/layout/WorkflowStepper';
import FileDropzone from '@/components/upload/FileDropzone';
import { Alert } from '@/components/ui/Alert';
import Card from '@/components/ui/Card';
import { Link as LinkIcon } from 'lucide-react';
import { Button } from '@/components/ui/Button';

function isSupportedFilename(name: string): boolean {
  return /\.(csv|xlsx|xls)$/i.test(name);
}

function inferNameFromUrl(input: string): string {
  try {
    const u = new URL(input);
    const fromPath = u.pathname.split('/').pop() || '';
    return decodeURIComponent(fromPath);
  } catch {
    return '';
  }
}

export default function UploadPage() {
  const router = useRouter();
  const [uploading, setUploading] = useState(false);
  const [importingFromUrl, setImportingFromUrl] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [presignedUrl, setPresignedUrl] = useState('');
  const [remoteFilename, setRemoteFilename] = useState('');
  const [analyses, setAnalyses] = useState<ReadyAnalysis[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);

  useEffect(() => {
    let mounted = true;
    const loadHistory = async () => {
      setLoadingHistory(true);
      setHistoryError(null);
      try {
        const rows = await reportBuilderApi.listReadyAnalyses();
        if (!mounted) return;
        setAnalyses(rows);
      } catch (err: unknown) {
        if (!mounted) return;
        setHistoryError(formatApiError(err, 'Failed to load analysis history'));
      } finally {
        if (mounted) setLoadingHistory(false);
      }
    };
    void loadHistory();
    return () => {
      mounted = false;
    };
  }, []);

  const onDrop = useCallback(
    async (acceptedFiles: File[]) => {
      if (acceptedFiles.length === 0) return;
      const file = acceptedFiles[0];
      if (!isSupportedFilename(file.name)) {
        setError('Please upload a CSV or Excel file (.csv, .xlsx, .xls)');
        return;
      }

      setUploading(true);
      setError(null);
      try {
        const dataset = await datasetsApi.uploadSmart(file);
        const datasetId = dataset.id ?? dataset.dataset_id;
        toast.success(`${file.name} uploaded successfully`);
        router.push(`/datasets/${datasetId}`);
      } catch (err: unknown) {
        const msg = formatApiError(err, 'Upload failed');
        setError(msg);
        toast.error(msg);
      } finally {
        setUploading(false);
      }
    },
    [router]
  );

  const handleImportFromPresignedUrl = useCallback(async () => {
    const url = presignedUrl.trim();
    if (!url) {
      setError('Enter a presigned URL');
      return;
    }
    let parsed: URL;
    try {
      parsed = new URL(url);
    } catch {
      setError('Enter a valid URL');
      return;
    }
    if (!/^https?:$/.test(parsed.protocol)) {
      setError('Only http/https URLs are supported');
      return;
    }

    setImportingFromUrl(true);
    setError(null);
    try {
      const dataset = await datasetsApi.importFromUrl(url, {
        filename: remoteFilename.trim() || undefined,
      });
      const datasetId = dataset.id ?? dataset.dataset_id;
      const name =
        dataset.filename ??
        (remoteFilename.trim() || inferNameFromUrl(url) || 'dataset');
      toast.success(`${name} imported successfully`);
      router.push(`/datasets/${datasetId}`);
    } catch (err: unknown) {
      const msg = formatApiError(
        err,
        'Failed to import from URL. Ensure the URL is valid and accessible.',
      );
      setError(msg);
      toast.error(msg);
    } finally {
      setImportingFromUrl(false);
    }
  }, [presignedUrl, remoteFilename, router]);

  return (
    <div>
      <WorkflowStepper currentStep={1} className="mb-8" />
      <PageHeader
        title="Dataset upload"
        description="Ingest CSV or Excel files for semantic analysis and audit-ready reporting."
      />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 items-stretch">
        <Card className="h-full p-5 border border-border bg-surface-card">
          <h3 className="font-semibold text-text mb-3">Upload from device</h3>
          <div className="h-[calc(100%-2rem)]">
            <FileDropzone onDrop={onDrop} uploading={uploading} />
          </div>
        </Card>

        <Card className="h-full p-5 border border-border bg-surface-card">
          <div className="flex items-start gap-3 mb-4">
            <div className="h-9 w-9 rounded-full bg-accent-muted flex items-center justify-center">
              <LinkIcon className="h-4 w-4 text-primary" aria-hidden />
            </div>
            <div>
              <h3 className="font-semibold text-text">Import from presigned URL</h3>
              <p className="text-sm text-text-muted">
                Paste a presigned S3 download URL.
              </p>
            </div>
          </div>
          <div className="space-y-3">
            <input
              type="url"
              placeholder="Paste your URL here"
              value={presignedUrl}
              onChange={(e) => setPresignedUrl(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-border rounded-lg bg-white focus:ring-2 focus:ring-accent/40"
            />
            <Button
              type="button"
              onClick={handleImportFromPresignedUrl}
              disabled={importingFromUrl || uploading}
              className="w-full sm:w-auto"
            >
              {importingFromUrl ? 'Importing…' : 'Import from URL'}
            </Button>
          </div>
        </Card>
      </div>
      {error && <Alert variant="error" className="mt-4">{error}</Alert>}
      <Card
        className="mt-6 border border-border bg-surface-card"
        title="History of analyzed reports"
        description="Recently completed analyses available for report generation."
      >
        {loadingHistory ? (
          <p className="text-sm text-text-muted">Loading history…</p>
        ) : historyError ? (
          <Alert variant="error">{historyError}</Alert>
        ) : analyses.length === 0 ? (
          <p className="text-sm text-text-muted">No completed analyses found yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left border-b border-border">
                  <th className="py-2 pr-4 font-medium text-text-muted">Analysis ID</th>
                  <th className="py-2 pr-4 font-medium text-text-muted">Dataset ID</th>
                  <th className="py-2 pr-4 font-medium text-text-muted">File</th>
                  <th className="py-2 pr-4 font-medium text-text-muted">Status</th>
                  <th className="py-2 pr-4 font-medium text-text-muted">Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {analyses.map((row) => (
                  <tr key={row.analysis_id} className="border-b border-border/40">
                    <td className="py-2 pr-4 font-mono">#{row.analysis_id}</td>
                    <td className="py-2 pr-4">{row.dataset_id}</td>
                    <td className="py-2 pr-4">{row.filename}</td>
                    <td className="py-2 pr-4 capitalize">{row.status || '—'}</td>
                    <td className="py-2 pr-4 text-text-muted">
                      {row.created_at ? new Date(row.created_at).toLocaleString() : '—'}
                    </td>
                    <td className="py-2 pr-4">
                      <Link
                        href={`/analysis/${row.analysis_id}`}
                        className="text-primary hover:underline text-xs"
                      >
                        Open →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
