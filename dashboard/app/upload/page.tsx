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
import { CheckCircle2 } from 'lucide-react';

export default function UploadPage() {
  const router = useRouter();
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [useCloud, setUseCloud] = useState(false);

  const onDrop = useCallback(
    async (acceptedFiles: File[]) => {
      if (acceptedFiles.length === 0) return;
      const file = acceptedFiles[0];
      if (!file.name.match(/\.(csv|xlsx|xls)$/i)) {
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

  return (
    <div>
      <WorkflowStepper currentStep={1} className="mb-8" />
      <PageHeader
        title="Upload dataset"
        description="Ingest CSV or Excel files for semantic analysis and audit-ready reporting."
      />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <label className="flex items-start gap-3 p-4 rounded-xl border border-border bg-surface-card cursor-pointer">
            <input
              type="checkbox"
              checked={useCloud}
              onChange={(e) => setUseCloud(e.target.checked)}
              className="mt-1 rounded border-border text-accent focus:ring-accent/40"
            />
            <span>
              <span className="font-medium text-text block">Cloud upload (R2)</span>
              <span className="text-sm text-text-muted">
                Use presigned URL when object storage is configured in the API.
              </span>
            </span>
          </label>
          <FileDropzone onDrop={onDrop} uploading={uploading} />
          {error && <Alert variant="error">{error}</Alert>}
        </div>
        <Card title="Before you upload">
          <ul className="space-y-3 text-sm text-text-muted">
            <li className="flex gap-2">
              <CheckCircle2 className="h-4 w-4 text-success shrink-0 mt-0.5" aria-hidden />
              Supported: CSV, XLSX, XLS
            </li>
            <li className="flex gap-2">
              <CheckCircle2 className="h-4 w-4 text-success shrink-0 mt-0.5" aria-hidden />
              First analysis may download the ML model (~1–3 min)
            </li>
            <li className="flex gap-2">
              <CheckCircle2 className="h-4 w-4 text-success shrink-0 mt-0.5" aria-hidden />
              Data stays on your configured API backend
            </li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
