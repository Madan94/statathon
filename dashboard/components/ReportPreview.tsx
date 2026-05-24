'use client';

import { useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/esm/Page/AnnotationLayer.css';
import 'react-pdf/dist/esm/Page/TextLayer.css';
import Card from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Download } from 'lucide-react';

pdfjs.GlobalWorkerOptions.workerSrc = `//cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.js`;

interface ReportPreviewProps {
  reportUrl: string;
  onDownload?: () => void;
}

export default function ReportPreview({ reportUrl, onDownload }: ReportPreviewProps) {
  const [numPages, setNumPages] = useState<number | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function onDocumentLoadSuccess({ numPages: n }: { numPages: number }) {
    setNumPages(n);
    setLoading(false);
  }

  function onDocumentLoadError(err: Error) {
    setError(err.message);
    setLoading(false);
  }

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-text">Report preview</h2>
        {onDownload && (
          <Button size="sm" onClick={onDownload}>
            <Download className="h-4 w-4" aria-hidden />
            Download
          </Button>
        )}
      </div>
      {loading && (
        <p className="text-center py-12 text-text-muted" role="status">
          Loading PDF…
        </p>
      )}
      {error && (
        <p className="text-center py-8 text-danger" role="alert">
          Error: {error}
        </p>
      )}
      {!loading && !error && (
        <>
          <div className="flex justify-center mb-4 border border-border rounded-lg overflow-hidden bg-surface">
            <Document
              file={reportUrl}
              onLoadSuccess={onDocumentLoadSuccess}
              onLoadError={onDocumentLoadError}
            >
              <Page
                pageNumber={pageNumber}
                renderTextLayer
                renderAnnotationLayer
                className="max-w-full"
              />
            </Document>
          </div>
          {numPages && numPages > 1 && (
            <div className="flex items-center justify-center gap-4">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setPageNumber((p) => Math.max(1, p - 1))}
                disabled={pageNumber === 1}
                aria-label="Previous page"
              >
                Previous
              </Button>
              <span className="text-sm text-text-muted" aria-live="polite">
                Page {pageNumber} of {numPages}
              </span>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setPageNumber((p) => Math.min(numPages, p + 1))}
                disabled={pageNumber === numPages}
                aria-label="Next page"
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
