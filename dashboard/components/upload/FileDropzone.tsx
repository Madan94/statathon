'use client';

import { useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { FileSpreadsheet, Upload } from 'lucide-react';
import { cn } from '@/lib/cn';

interface FileDropzoneProps {
  onDrop: (files: File[]) => void;
  uploading?: boolean;
  disabled?: boolean;
}

export default function FileDropzone({ onDrop, uploading, disabled }: FileDropzoneProps) {
  const handleDrop = useCallback(
    (accepted: File[]) => {
      onDrop(accepted);
    },
    [onDrop]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: handleDrop,
    accept: {
      'text/csv': ['.csv'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls'],
    },
    multiple: false,
    disabled: disabled || uploading,
  });

  return (
    <div
      {...getRootProps()}
      className={cn(
        'relative rounded-xl border-2 border-dashed p-12 text-center cursor-pointer transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
        isDragActive
          ? 'border-accent bg-accent-muted/50'
          : 'border-border hover:border-accent/60 bg-surface-card',
        (disabled || uploading) && 'pointer-events-none opacity-60'
      )}
    >
      <input {...getInputProps()} aria-label="Upload dataset file" />
      {uploading ? (
        <div className="space-y-4">
          <div
            className="mx-auto h-12 w-12 animate-spin rounded-full border-2 border-border border-t-accent"
            role="status"
            aria-label="Uploading"
          />
          <p className="text-text-muted">Uploading…</p>
          <div className="mx-auto max-w-xs h-1.5 rounded-full bg-border overflow-hidden">
            <div className="h-full w-1/2 bg-accent animate-pulse rounded-full" />
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-accent-muted">
            {isDragActive ? (
              <Upload className="h-7 w-7 text-accent" aria-hidden />
            ) : (
              <FileSpreadsheet className="h-7 w-7 text-primary" aria-hidden />
            )}
          </div>
          <div>
            <p className="text-lg font-medium text-text">
              {isDragActive ? 'Drop your file here' : 'Drag & drop CSV or Excel'}
            </p>
            <p className="text-sm text-text-muted mt-1">or click to browse · CSV, XLSX, XLS</p>
          </div>
        </div>
      )}
    </div>
  );
}
