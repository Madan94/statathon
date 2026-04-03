'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { reportsApi } from '@/lib/api';
import ReportPreview from '@/components/ReportPreview';

export default function ReportPage() {
  const params = useParams();
  const id = Number(params.id);
  const [reportUrl, setReportUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    reportsApi
      .download(id)
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        setReportUrl(url);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  const handleDownload = () => {
    if (reportUrl) {
      const a = document.createElement('a');
      a.href = reportUrl;
      a.download = `report-${id}.pdf`;
      a.click();
    }
  };

  if (loading) {
    return <div className="min-h-screen flex items-center justify-center">Loading report...</div>;
  }

  if (!reportUrl) {
    return <div className="min-h-screen flex items-center justify-center">Report not found</div>;
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black py-16 px-4">
      <div className="max-w-6xl mx-auto">
        <ReportPreview reportUrl={reportUrl} onDownload={handleDownload} />
      </div>
    </div>
  );
}

