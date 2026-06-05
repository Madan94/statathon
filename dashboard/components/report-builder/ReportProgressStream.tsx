'use client';

import { useEffect, useRef, useState } from 'react';
import { cn } from '@/lib/cn';

interface ProgressEvent {
  stage: string;
  pct: number;
  message: string;
}

const STAGE_LABELS: Record<string, string> = {
  binding: 'Resolving Entities',
  extraction: 'Extracting Facts',
  consensus: 'Verifying Claims',
  rendering: 'Generating Report',
  complete: 'Complete',
  error: 'Error',
};

export default function ReportProgressStream({
  jobId,
  apiBase = '',
  onComplete,
  onError,
  className,
}: {
  jobId: number;
  apiBase?: string;
  onComplete?: () => void;
  onError?: (msg: string) => void;
  className?: string;
}) {
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [status, setStatus] = useState<'connecting' | 'streaming' | 'done' | 'error'>('connecting');
  const [currentPct, setCurrentPct] = useState(0);
  const [currentStage, setCurrentStage] = useState('');
  const [currentMessage, setCurrentMessage] = useState('Connecting...');
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const url = `${apiBase}/api/report-builder/jobs/${jobId}/progress/stream`;
    const es = new EventSource(url);
    esRef.current = es;
    setStatus('streaming');

    es.addEventListener('progress', (e) => {
      try {
        const data: ProgressEvent = JSON.parse(e.data);
        if (data.pct === -1) return; // keepalive
        setEvents((prev) => [...prev, data]);
        setCurrentPct(data.pct);
        setCurrentStage(data.stage);
        setCurrentMessage(data.message);
      } catch {
        // ignore parse errors
      }
    });

    es.addEventListener('complete', (e) => {
      setStatus('done');
      setCurrentPct(100);
      setCurrentMessage('Report generation complete');
      es.close();
      onComplete?.();
    });

    es.addEventListener('error', (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data || '{}');
        setCurrentMessage(data.message || 'An error occurred');
      } catch {
        setCurrentMessage('Connection lost');
      }
      setStatus('error');
      es.close();
      onError?.(currentMessage);
    });

    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        setStatus('error');
        setCurrentMessage('Connection closed');
      }
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [jobId, apiBase]);

  const stageLabel = STAGE_LABELS[currentStage] || currentStage;

  return (
    <div className={cn('rounded-lg border p-4 bg-white shadow-sm', className)}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-700">Report Generation</h3>
        <span
          className={cn(
            'px-2 py-0.5 text-xs rounded-full font-medium',
            status === 'streaming' && 'bg-blue-100 text-blue-700',
            status === 'done' && 'bg-green-100 text-green-700',
            status === 'error' && 'bg-red-100 text-red-700',
            status === 'connecting' && 'bg-yellow-100 text-yellow-700'
          )}
        >
          {status === 'streaming' ? 'In Progress' : status === 'done' ? 'Complete' : status === 'error' ? 'Failed' : 'Connecting'}
        </span>
      </div>

      {/* Progress bar */}
      <div className="w-full bg-gray-200 rounded-full h-2.5 mb-2">
        <div
          className={cn(
            'h-2.5 rounded-full transition-all duration-300',
            status === 'error' ? 'bg-red-500' : status === 'done' ? 'bg-green-500' : 'bg-blue-600'
          )}
          style={{ width: `${Math.max(0, Math.min(100, currentPct))}%` }}
        />
      </div>

      {/* Stage info */}
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>{stageLabel}</span>
        <span>{currentPct}%</span>
      </div>

      {/* Message */}
      <p className="mt-2 text-xs text-gray-600 truncate">{currentMessage}</p>

      {/* Recent events log */}
      {events.length > 0 && (
        <details className="mt-3">
          <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-600">
            Activity log ({events.length} events)
          </summary>
          <ul className="mt-1 max-h-32 overflow-y-auto space-y-0.5">
            {events.slice(-10).map((evt, i) => (
              <li key={i} className="text-xs text-gray-500 flex justify-between">
                <span>{STAGE_LABELS[evt.stage] || evt.stage}: {evt.message}</span>
                <span className="text-gray-400">{evt.pct}%</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
