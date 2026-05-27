'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { datasetsApi } from '@/lib/api';
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

function inferNameFromType(contentType: string | null): string {
  const lower = (contentType || '').toLowerCase();
  if (lower.includes('text/csv')) return `dataset-${Date.now()}.csv`;
  if (lower.includes('application/vnd.ms-excel')) return `dataset-${Date.now()}.xls`;
  if (lower.includes('spreadsheetml.sheet')) return `dataset-${Date.now()}.xlsx`;
  return '';
}

export default function UploadPage() {
  const router = useRouter();
  const [uploading, setUploading] = useState(false);
  const [importingFromUrl, setImportingFromUrl] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [useCloud, setUseCloud] = useState(false);
  const [presignedUrl, setPresignedUrl] = useState('');
  const [remoteFilename, setRemoteFilename] = useState('');

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
        const dataset = useCloud
          ? await datasetsApi.presignedUpload(file)
          : await datasetsApi.upload(file);
        const datasetId = dataset.id ?? dataset.dataset_id;
        toast.success(`${file.name} uploaded successfully`);
        router.push(`/datasets/${datasetId}`);
      } catch (err: unknown) {
        const ax = err as { response?: { data?: { detail?: string } }; message?: string };
        const msg = ax.response?.data?.detail || ax.message || 'Upload failed';
        setError(msg);
        toast.error(msg);
      } finally {
        setUploading(false);
      }
    },
    [router, useCloud]
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
      const res = await fetch(url, { method: 'GET' });
      if (!res.ok) {
        throw new Error(`Could not fetch file from URL (${res.status} ${res.statusText})`);
      }

      const blob = await res.blob();
      const guessed =
        remoteFilename.trim() || inferNameFromUrl(url) || inferNameFromType(res.headers.get('content-type'));
      const filename = guessed || `dataset-${Date.now()}.csv`;

      if (!isSupportedFilename(filename)) {
        throw new Error('URL must point to .csv, .xls, or .xlsx file');
      }

      const file = new File([blob], filename, { type: blob.type || 'application/octet-stream' });
      const dataset = useCloud
        ? await datasetsApi.presignedUpload(file)
        : await datasetsApi.upload(file);
      const datasetId = dataset.id ?? dataset.dataset_id;
      toast.success(`${filename} imported successfully`);
      router.push(`/datasets/${datasetId}`);
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string } }; message?: string };
      const msg =
        ax.response?.data?.detail ||
        ax.message ||
        'Failed to import from URL. Ensure the URL is valid and accessible.';
      setError(msg);
      toast.error(msg);
    } finally {
      setImportingFromUrl(false);
    }
  }, [presignedUrl, remoteFilename, useCloud, router]);

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
                Paste a temporary file URL to import CSV/Excel directly.
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
            <input
              type="text"
              placeholder="Name your file"
              value={remoteFilename}
              onChange={(e) => setRemoteFilename(e.target.value)}
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
    </div>
  );
}
