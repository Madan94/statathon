'use client';
import { useParams } from 'next/navigation';
import { CanvasShell } from '@/components/report-canvas/CanvasShell';

export default function ReportCanvasPage() {
  const params = useParams();
  const templateId = params.templateId as string;
  const signature = params.signature as string;
  return <CanvasShell templateId={templateId} signature={signature} />;
}