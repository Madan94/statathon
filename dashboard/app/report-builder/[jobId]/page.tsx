'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  Loader2,
  RefreshCw,
  Download,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Pencil,
  Save,
  ShieldCheck,
  BookOpen,
  Database,
  Network,
  BarChart3,
  Hash,
  MessageSquare,
  Send,
  GripVertical,
  Trash2,
  FileUp,
  Sparkles,
  X,
} from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import DeliveryPanel from '@/components/report-builder/DeliveryPanel';
import DeepAgentPanel from '@/components/report-builder/DeepAgentPanel';
import {
  reportBuilderApi,
  ChatTurn,
  JobCanvasResponse,
  RenderedBlock,
  VerifierVerdict,
} from '@/lib/api';

const DRAG_MIME = 'application/x-statathon-block';

function isBlockDrag(dt: DataTransfer): boolean {
  return Array.from(dt.types).some(
    (t) => t === DRAG_MIME || t === 'text/plain'
  );
}

function parseDragPayload(dt: DataTransfer): {
  block: RenderedBlock;
  fromCanvas: boolean;
} | null {
  const raw = dt.getData(DRAG_MIME) || dt.getData('text/plain');
  if (!raw) return null;
  try {
    const payload = JSON.parse(raw) as { block: RenderedBlock; fromCanvas: boolean };
    if (!payload?.block) return null;
    return payload;
  } catch {
    return null;
  }
}

function writeDragPayload(dt: DataTransfer, block: RenderedBlock, fromCanvas: boolean) {
  const raw = JSON.stringify({ block, fromCanvas });
  dt.setData(DRAG_MIME, raw);
  dt.setData('text/plain', raw);
}

export default function JobCanvasPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const router = useRouter();
  const jobIdNum = Number(jobId);

  const [data, setData] = useState<JobCanvasResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(true);
  const [activeTab, setActiveTab] = useState<'classic' | 'deep'>('deep');
  const [templateModalOpen, setTemplateModalOpen] = useState(false);
  const pollingRef = useRef<boolean>(false);

  const refresh = async (fullCanvas = false) => {
    try {
      if (fullCanvas || !data) {
        const d = await reportBuilderApi.getCanvas(jobIdNum);
        setData(d);
      } else {
        const job = await reportBuilderApi.getJob(jobIdNum);
        setData((prev) =>
          prev
            ? {
                ...prev,
                status: job.status,
                stage: job.stage ?? prev.stage,
              }
            : prev,
        );
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load job');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!Number.isFinite(jobIdNum)) return;
    refresh(true);
  }, [jobIdNum]);

  useEffect(() => {
    if (!data) return;
    const inProgress =
      data.status === 'pending' ||
      data.status === 'running' ||
      data.status === 'awaiting_verification';
    if (!inProgress) {
      pollingRef.current = false;
      if (data.status === 'exported' || data.status === 'verified' || data.status === 'failed') {
        void refresh(true);
      }
      return;
    }
    if (pollingRef.current) return;
    pollingRef.current = true;
    const interval = setInterval(() => {
      void refresh(false);
    }, 2500);
    return () => {
      clearInterval(interval);
      pollingRef.current = false;
    };
  }, [data?.status]);

  const onDownload = async () => {
    try {
      const blob = await reportBuilderApi.downloadPdf(jobIdNum);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `statathon-report-${jobIdNum}.pdf`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      a.remove();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed');
    }
  };

  const onReExport = async () => {
    try {
      await reportBuilderApi.reExport(jobIdNum);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Re-export failed');
    }
  };

  // Drop a chat-result (or any) block into a target section.
  const handleDrop = async (
    targetSection: string,
    sourceBlock: RenderedBlock,
    fromCanvas: boolean,
    position?: number
  ) => {
    try {
      if (fromCanvas) {
        await reportBuilderApi.moveBlock(jobIdNum, {
          block_id: sourceBlock.block_id,
          target_section: targetSection,
          target_position: position,
        });
      } else {
        const payload = { ...sourceBlock } as Record<string, unknown>;
        delete (payload as { block_id?: string }).block_id; // server assigns fresh ID
        await reportBuilderApi.insertBlock(jobIdNum, {
          section: targetSection,
          block: payload,
          position,
        });
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Drop failed');
    }
  };

  const handleDelete = async (blockId: string) => {
    if (!confirm('Remove this block from the report?')) return;
    try {
      await reportBuilderApi.deleteBlock(jobIdNum, blockId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    }
  };

  if (loading) {
    return (
      <>
        <div className="flex items-center gap-2 text-text-muted">
          <Loader2 className="h-5 w-5 animate-spin" /> Loading job…
        </div>
      </>
    );
  }

  if (!data) {
    return (
      <>
        <Alert variant="error">{error || 'Job not found'}</Alert>
        <Button className="mt-4" onClick={() => router.push('/report/report-ast-generator')}>
          ← Back
        </Button>
      </>
    );
  }

  const canvas = data.canvas;
  const summary = canvas?.summary || {};

  return (
    <>
      <PageHeader
        title={canvas?.template_name || `Report Job #${data.id}`}
        description={`Analysis ${data.analysis_id} · ${data.status}${data.stage ? ' · ' + data.stage : ''}`}
        actions={
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => router.push('/report/report-ast-generator')}
            >
              ← Back
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setTemplateModalOpen(true)}
              title="Upload a historical MoSPI PDF to extract a new template"
            >
              <FileUp className="h-4 w-4 mr-1" /> Change template
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setChatOpen((v) => !v)}
            >
              <MessageSquare className="h-4 w-4 mr-1" />
              {chatOpen ? 'Hide BI' : 'Open BI'}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => refresh(true)}>
              <RefreshCw className="h-4 w-4 mr-1" /> Refresh
            </Button>
            <Button size="sm" variant="outline" onClick={onReExport}>
              Re-export PDF
            </Button>
            <Button
              size="sm"
              onClick={onDownload}
              disabled={data.status !== 'exported' || !data.final_pdf_path}
            >
              <Download className="h-4 w-4 mr-1" /> PDF
            </Button>
          </>
        }
      />

      {error && (
        <Alert variant="error" className="mb-4">
          {error}
        </Alert>
      )}

      {data?.status === 'exported' && (
        <DeliveryPanel
          jobId={jobIdNum}
          deliveryLog={data.delivery_log}
          onDelivered={refresh}
        />
      )}

      <div className={chatOpen ? 'lg:pr-[420px] transition-[padding] duration-200' : ''}>
        {/* ----- Canvas column (full width) ----- */}
        <div className="space-y-6">
          {Object.keys(summary).length > 0 && (
            <Card title="Analytics Summary" description="All metrics derived from the analysis pipeline.">
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                {Object.entries(summary).map(([k, v]) => (
                  <div key={k} className="rounded-lg border border-border bg-surface p-3">
                    <p className="text-xs text-text-muted">{k.replace(/_/g, ' ')}</p>
                    <p className="text-sm font-semibold text-text mt-1 break-words">{String(v)}</p>
                  </div>
                ))}
              </div>
              {data.content_hash && (
                <div className="mt-4 flex items-center gap-2 text-xs text-text-muted font-mono">
                  <Hash className="h-3 w-3" /> {data.content_hash}
                </div>
              )}
            </Card>
          )}

          {(data.status === 'pending' || data.status === 'running') && (
            <Alert variant="warning">
              <div className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Running pipeline · current stage:{' '}
                <span className="font-mono">{data.stage || '—'}</span>
              </div>
            </Alert>
          )}

          {canvas &&
            canvas.sections.map((sect) => (
              <SectionDropZone
                key={sect.section}
                section={sect.section}
                blocks={sect.blocks}
                onDrop={handleDrop}
                onDelete={handleDelete}
                onUpdate={(updated) => {
                  setData((prev) => {
                    if (!prev || !prev.canvas) return prev;
                    const next = { ...prev, canvas: { ...prev.canvas } };
                    next.canvas.sections = next.canvas.sections.map((s) => ({
                      ...s,
                      blocks: s.blocks.map((bb) =>
                        bb.block_id === updated.block_id ? updated : bb
                      ),
                    }));
                    return next;
                  });
                }}
                jobId={jobIdNum}
              />
            ))}

          {/* Always allow dropping into a 'bi_findings' section even if not present yet */}
          {canvas &&
            !canvas.sections.some((s) => s.section === 'bi_findings') && (
              <SectionDropZone
                section="bi_findings"
                blocks={[]}
                onDrop={handleDrop}
                onDelete={handleDelete}
                onUpdate={() => {}}
                jobId={jobIdNum}
                emptyHint="Drag a chat result here to add a 'BI Findings' section."
              />
            )}
        </div>

      </div>

      {/* ----- DeepAgent BI Drawer (fixed right panel) ----- */}
      {chatOpen && (
        <div className="fixed top-0 right-0 h-screen w-[420px] z-50 flex flex-col border-l border-border bg-surface-card shadow-2xl">
          {/* Tab header */}
          <div className="flex items-center border-b border-border shrink-0">
            <button
              className={`flex-1 py-2.5 text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors ${
                activeTab === 'deep'
                  ? 'text-primary border-b-2 border-primary bg-primary/5'
                  : 'text-text-muted hover:text-text'
              }`}
              onClick={() => setActiveTab('deep')}
            >
              <Sparkles className="h-3.5 w-3.5" />
              DeepAgent BI
            </button>
            <button
              className={`flex-1 py-2.5 text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors ${
                activeTab === 'classic'
                  ? 'text-primary border-b-2 border-primary bg-primary/5'
                  : 'text-text-muted hover:text-text'
              }`}
              onClick={() => setActiveTab('classic')}
            >
              <MessageSquare className="h-3.5 w-3.5" />
              Classic Chat
            </button>
            <button
              className="px-3 py-2.5 text-text-muted hover:text-text"
              onClick={() => setChatOpen(false)}
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Panel content */}
          <div className="flex-1 min-h-0 overflow-hidden">
            {activeTab === 'deep' ? (
              <DeepAgentPanel
                jobId={jobIdNum}
                onDragBlock={(block) => handleDrop('bi_findings', block, false)}
              />
            ) : (
              <ChatPanel
                jobId={jobIdNum}
                onClose={() => setChatOpen(false)}
                onInsertBlock={(block) => handleDrop('bi_findings', block, false)}
              />
            )}
          </div>
        </div>
      )}

      {templateModalOpen && (
        <TemplateUploaderModal
          analysisId={data.analysis_id}
          onClose={() => setTemplateModalOpen(false)}
          onJobCreated={(newJobId) => {
            setTemplateModalOpen(false);
            router.push(`/report-builder/${newJobId}`);
          }}
        />
      )}
    </>
  );
}

// ---------------- Section drop zone ----------------

function SectionDropZone({
  section,
  blocks,
  onDrop,
  onDelete,
  onUpdate,
  jobId,
  emptyHint,
}: {
  section: string;
  blocks: RenderedBlock[];
  onDrop: (
    section: string,
    block: RenderedBlock,
    fromCanvas: boolean,
    position?: number
  ) => void | Promise<void>;
  onDelete: (blockId: string) => void | Promise<void>;
  onUpdate: (b: RenderedBlock) => void;
  jobId: number;
  emptyHint?: string;
}) {
  const [over, setOver] = useState(false);

  const onDragOver = (e: React.DragEvent) => {
    if (!isBlockDrag(e.dataTransfer)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setOver(true);
  };

  const onDragLeave = (e: React.DragEvent) => {
    const related = e.relatedTarget as Node | null;
    if (related && e.currentTarget.contains(related)) return;
    setOver(false);
  };

  const onDropEvt = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setOver(false);
    const payload = parseDragPayload(e.dataTransfer);
    if (!payload) return;
    void onDrop(section, payload.block, payload.fromCanvas);
  };

  return (
    <section>
      <h2 className="text-sm font-semibold text-primary uppercase tracking-wide mb-3 flex items-center gap-2">
        {sectionIcon(section)}
        {section.replace(/_/g, ' ')}
      </h2>
      <div
        onDragOver={onDragOver}
        onDragOverCapture={onDragOver}
        onDragLeave={onDragLeave}
        onDropCapture={onDropEvt}
        className={
          'space-y-3 rounded-xl border-2 border-dashed p-2 min-h-[5rem] transition-colors ' +
          (over ? 'border-accent bg-accent/5' : 'border-border/40')
        }
      >
        {blocks.length === 0 && emptyHint && (
          <p className="text-xs text-text-muted italic px-2 py-4 pointer-events-none select-none">
            {emptyHint}
          </p>
        )}
        {blocks.map((b) => (
          <BlockCard
            key={b.block_id}
            block={b}
            jobId={jobId}
            section={section}
            onUpdate={onUpdate}
            onDelete={onDelete}
          />
        ))}
      </div>
    </section>
  );
}

function sectionIcon(name: string) {
  const cn = 'h-4 w-4';
  if (name.includes('exec')) return <BookOpen className={cn} />;
  if (name.includes('overview') || name.includes('data')) return <Database className={cn} />;
  if (name.includes('quality')) return <ShieldCheck className={cn} />;
  if (name.includes('relation')) return <Network className={cn} />;
  if (name.includes('finding') || name.includes('recommend') || name.includes('bi'))
    return <BarChart3 className={cn} />;
  return null;
}

// ---------------- Block card (in canvas, draggable) ----------------

function BlockCard({
  block,
  jobId,
  section,
  onUpdate,
  onDelete,
}: {
  block: RenderedBlock;
  jobId: number;
  section: string;
  onUpdate: (b: RenderedBlock) => void;
  onDelete: (id: string) => void | Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);

  const onRegenerate = async () => {
    setBusy(true);
    try {
      const updated = await reportBuilderApi.regenerateBlock(jobId, block.block_id);
      onUpdate(updated);
    } finally {
      setBusy(false);
    }
  };

  const startEdit = () => {
    const txt =
      typeof block.payload === 'object' && block.payload && 'text' in block.payload
        ? String((block.payload as { text?: unknown }).text || '')
        : '';
    setDraft(txt);
    setEditing(true);
  };

  const saveEdit = async () => {
    setBusy(true);
    try {
      const before =
        typeof block.payload === 'object' && block.payload && 'text' in block.payload
          ? String((block.payload as { text?: unknown }).text || '')
          : '';
      await reportBuilderApi.recordCorrection(jobId, block.block_id, {
        before,
        after: draft,
      });
      onUpdate({
        ...block,
        payload: { ...block.payload, text: draft },
        version: block.version + 1,
      });
      setEditing(false);
    } finally {
      setBusy(false);
    }
  };

  const onDragStart = (e: React.DragEvent) => {
    writeDragPayload(e.dataTransfer, block, true);
    e.dataTransfer.effectAllowed = 'move';
  };

  return (
    <Card>
      <div className="flex items-start justify-between mb-3 gap-2">
        <div
          className="cursor-grab pt-1"
          draggable
          onDragStart={onDragStart}
          title="Drag to move between sections"
        >
          <GripVertical className="h-4 w-4 text-text-muted" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-text">{block.title}</h3>
          <div className="text-xs text-text-muted flex items-center gap-2 mt-1 flex-wrap">
            <Badge variant="muted">{block.kind}</Badge>
            {block.route && (
              <span className="font-mono">via {block.route.engine}</span>
            )}
            <VerifierBadge verifier={block.verifier} />
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {block.kind === 'narrative' && !editing && (
            <>
              <button
                onClick={onRegenerate}
                disabled={busy}
                className="text-xs text-text-muted hover:text-text inline-flex items-center gap-1"
              >
                {busy ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <RefreshCw className="h-3 w-3" />
                )}
                Regenerate
              </button>
              <button
                onClick={startEdit}
                className="text-xs text-text-muted hover:text-text inline-flex items-center gap-1"
              >
                <Pencil className="h-3 w-3" /> Edit
              </button>
            </>
          )}
          <button
            onClick={() => onDelete(block.block_id)}
            title="Delete from report"
            className="text-xs text-danger/70 hover:text-danger inline-flex items-center gap-1"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      </div>

      <BlockBody block={block} editing={editing} draft={draft} setDraft={setDraft} />

      {editing && (
        <div className="flex gap-2 mt-3">
          <Button size="sm" onClick={saveEdit} disabled={busy}>
            <Save className="h-4 w-4 mr-1" /> Save (LTM record)
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </div>
      )}

      {block.verifier && block.verifier.checks.length > 0 && (
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer text-text-muted hover:text-text">
            Verifier details ({block.verifier.checks.length} claims)
          </summary>
          <table className="w-full mt-2 text-xs">
            <thead>
              <tr className="text-left text-text-muted">
                <th className="pr-2">Claim</th>
                <th className="pr-2">Claimed</th>
                <th className="pr-2">Computed</th>
                <th className="pr-2">Status</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {block.verifier.checks.map((c, i) => (
                <tr key={i} className="border-t border-border/40">
                  <td className="pr-2 font-mono">{c.claim}</td>
                  <td className="pr-2">{c.claimed_value}</td>
                  <td className="pr-2">{c.computed_value ?? '—'}</td>
                  <td className="pr-2">{c.status}</td>
                  <td className="text-text-muted">{c.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </Card>
  );
}

function VerifierBadge({ verifier }: { verifier?: VerifierVerdict | null }) {
  if (!verifier) return null;
  const map: Record<string, { v: 'success' | 'warning' | 'danger'; icon: React.ReactNode }> = {
    pass: { v: 'success', icon: <CheckCircle2 className="h-3 w-3 mr-1" /> },
    warn: { v: 'warning', icon: <AlertTriangle className="h-3 w-3 mr-1" /> },
    fail: { v: 'danger', icon: <XCircle className="h-3 w-3 mr-1" /> },
  };
  const entry = map[verifier.overall_status] || map.warn;
  return (
    <Badge variant={entry.v}>
      <span className="inline-flex items-center">
        {entry.icon}Verifier: {verifier.overall_status}
      </span>
    </Badge>
  );
}

// ---------------- Block body by kind ----------------

function BlockBody({
  block,
  editing,
  draft,
  setDraft,
}: {
  block: RenderedBlock;
  editing: boolean;
  draft: string;
  setDraft: (s: string) => void;
}) {
  const payload = block.payload || {};

  if (block.kind === 'narrative') {
    if (editing) {
      return (
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="w-full min-h-[140px] rounded-lg border border-border p-3 text-sm font-serif leading-relaxed"
        />
      );
    }
    const text = (payload as { text?: string }).text || '(no narrative)';
    return (
      <p className="text-sm leading-relaxed text-text whitespace-pre-wrap font-serif">
        {text}
      </p>
    );
  }

  if (block.kind === 'metric') {
    const metrics = (payload as { metrics?: Record<string, unknown> }).metrics || {};
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {Object.entries(metrics).map(([k, v]) => (
          <div key={k} className="rounded-lg border border-border bg-surface p-2">
            <p className="text-xs text-text-muted">{k}</p>
            <p className="text-sm font-mono break-all">{String(v)}</p>
          </div>
        ))}
      </div>
    );
  }

  if (block.kind === 'table') {
    const rows = ((payload as { rows?: Array<Record<string, unknown>> }).rows) || [];
    const cols = ((payload as { columns?: string[] }).columns) || [];
    if (!rows.length || !cols.length) {
      return <p className="text-xs text-text-muted">(no rows)</p>;
    }
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border">
              {cols.map((c) => (
                <th key={c} className="py-1 pr-3 text-left font-medium text-text-muted">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 50).map((r, i) => (
              <tr key={i} className="border-b border-border/40">
                {cols.map((c) => (
                  <td key={c} className="py-1 pr-3">
                    {formatCell(r[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > 50 && (
          <p className="text-xs text-text-muted mt-1">
            (showing first 50 of {rows.length} rows; PDF includes 60)
          </p>
        )}
      </div>
    );
  }

  if (block.kind === 'chart') {
    const labels = ((payload as { labels?: string[] }).labels) || [];
    const values = ((payload as { values?: number[] }).values) || [];
    if (!labels.length) {
      return <p className="text-xs text-text-muted">(no chart data)</p>;
    }
    const max = Math.max(...values, 1);
    return (
      <div className="space-y-1">
        {labels.map((lab, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="w-32 truncate text-text-muted">{lab}</span>
            <div className="flex-1 bg-border/40 rounded h-3 relative overflow-hidden">
              <div
                className="absolute inset-y-0 left-0 bg-primary"
                style={{ width: `${(Number(values[i]) / max) * 100}%` }}
              />
            </div>
            <span className="w-12 text-right font-mono">{values[i]}</span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <pre className="text-xs text-text-muted overflow-x-auto">
      {JSON.stringify(payload, null, 2)}
    </pre>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(3);
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

// ---------------- Chat side panel ----------------

function ChatPanel({
  jobId,
  onClose,
  onInsertBlock,
}: {
  jobId: number;
  onClose: () => void;
  onInsertBlock?: (block: RenderedBlock) => void | Promise<void>;
}) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    reportBuilderApi
      .chatHistory(jobId)
      .then((r) => setTurns(r.turns))
      .catch(() => {});
  }, [jobId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [turns]);

  const send = async () => {
    const q = query.trim();
    if (!q || busy) return;
    setBusy(true);
    setQuery('');
    setTurns((prev) => [
      ...prev,
      { role: 'user', text: q, created_at: new Date().toISOString() },
    ]);
    try {
      const turn = await reportBuilderApi.chat(jobId, q);
      setTurns((prev) => [...prev, turn]);
    } catch (err) {
      const msg =
        err && typeof err === 'object' && 'response' in err
          ? String((err as { response?: { data?: { detail?: string } } }).response?.data?.detail || '')
          : err instanceof Error
            ? err.message
            : 'Chat failed';
      setTurns((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: `Error: ${msg}`,
          created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside
      className="fixed top-16 right-3 bottom-3 w-[400px] max-w-[calc(100vw-1.5rem)] z-30 flex flex-col rounded-2xl border border-border bg-surface-card shadow-2xl overflow-hidden"
      aria-label="BI Chat"
    >
      <header className="p-4 border-b border-border flex items-center justify-between bg-surface-card shrink-0">
        <div>
          <h3 className="font-semibold text-text flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-primary" /> BI Chat
          </h3>
          <p className="text-[11px] text-text-muted mt-0.5">
            Phases 1-5 logic · drag results into the report
          </p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close chat"
          className="p-1 rounded hover:bg-border/50 text-text-muted hover:text-text"
        >
          <X className="h-4 w-4" />
        </button>
      </header>
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3 bg-surface/30">
          {turns.length === 0 && (
            <div className="text-xs text-text-muted px-2 py-4 space-y-2">
              <p className="font-medium">Try asking:</p>
              <ul className="list-disc list-inside space-y-1">
                <li>show missing values per column</li>
                <li>top 10 by population</li>
                <li>count of rows by region</li>
                <li>which columns influence GDP</li>
                <li>find outliers with z-score</li>
                <li>summarise data quality issues</li>
              </ul>
            </div>
          )}
          {turns.map((t, i) => (
            <ChatBubble key={i} turn={t} onInsertBlock={onInsertBlock} />
          ))}
          {busy && (
            <div className="text-xs text-text-muted flex items-center gap-2">
              <Loader2 className="h-3 w-3 animate-spin" /> Running phases 1-5…
            </div>
          )}
        </div>
        <footer className="p-3 border-t border-border bg-surface-card">
          <div className="flex items-end gap-2">
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Ask about the data…"
              rows={2}
              className="flex-1 resize-none rounded-lg border border-border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
            />
            <Button size="sm" onClick={send} disabled={busy || !query.trim()}>
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </footer>
    </aside>
  );
}

function ChatBubble({
  turn,
  onInsertBlock,
}: {
  turn: ChatTurn;
  onInsertBlock?: (block: RenderedBlock) => void | Promise<void>;
}) {
  if (turn.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="bg-primary text-white text-sm rounded-2xl rounded-br-sm px-3 py-2 max-w-[85%] whitespace-pre-wrap">
          {turn.text}
        </div>
      </div>
    );
  }
  return (
    <div className="flex justify-start">
      <div className="bg-surface-card border border-border text-sm rounded-2xl rounded-bl-sm px-3 py-2 max-w-[95%] w-full">
        {turn.route && (
          <div className="flex items-center gap-2 mb-1 text-[10px] text-text-muted">
            <Badge variant="muted">{turn.route.engine}</Badge>
            <span className="italic">{turn.route.rationale}</span>
            <VerifierBadge verifier={turn.verifier} />
          </div>
        )}
        <p className="whitespace-pre-wrap text-text">{turn.text}</p>
        {turn.block && (
          <div className="mt-2">
            <DraggableProposal
              block={turn.block}
              onInsert={
                onInsertBlock ? () => onInsertBlock(turn.block!) : undefined
              }
            />
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------- Draggable proposal card (in chat) ----------------

// ---------------- Template Uploader (in-canvas modal) ----------------

function TemplateUploaderModal({
  analysisId,
  onClose,
  onJobCreated,
}: {
  analysisId: number;
  onClose: () => void;
  onJobCreated: (jobId: number) => void;
}) {
  const [step, setStep] = useState<'pick' | 'uploading' | 'preview' | 'generating'>('pick');
  const [name, setName] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [extractedAst, setExtractedAst] = useState<{
    id: number;
    name: string;
    page_count?: number | null;
    extraction_method?: string | null;
    source_hash?: string | null;
    ast: { blocks?: Array<Record<string, unknown>> };
  } | null>(null);

  const onPick = (f: File | null) => {
    setError(null);
    if (!f) return;
    if (!/\.pdf$/i.test(f.name) && f.type !== 'application/pdf') {
      setError('Templates must be a PDF (MoSPI bulletins are PDF). CSV/Excel goes through the dataset Upload page.');
      return;
    }
    setFile(f);
    if (!name) setName(f.name.replace(/\.pdf$/i, ''));
  };

  const upload = async () => {
    if (!file || !name.trim()) return;
    setError(null);
    setStep('uploading');
    try {
      const out = await reportBuilderApi.uploadTemplate(name.trim(), file);
      setExtractedAst({
        id: out.id,
        name: out.name,
        page_count: out.page_count,
        extraction_method: out.extraction_method,
        source_hash: out.source_hash,
        ast: (out.ast as { blocks?: Array<Record<string, unknown>> }) || { blocks: [] },
      });
      setStep('preview');
    } catch (err) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null;
      setError(detail || (err instanceof Error ? err.message : 'Upload failed'));
      setStep('pick');
    }
  };

  const generate = async () => {
    if (!extractedAst) return;
    setStep('generating');
    setError(null);
    try {
      const job = await reportBuilderApi.generate(analysisId, extractedAst.id);
      onJobCreated(job.id);
    } catch (err) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null;
      setError(detail || (err instanceof Error ? err.message : 'Generation failed'));
      setStep('preview');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-surface-card rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        <header className="flex items-center justify-between p-5 border-b border-border">
          <div className="flex items-center gap-3">
            <FileUp className="h-5 w-5 text-primary" />
            <div>
              <h2 className="font-semibold text-text">Upload MoSPI template (PDF)</h2>
              <p className="text-xs text-text-muted">
                Phase 0: vision-spatial extraction → SGLang AST
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-border/50 text-text-muted hover:text-text"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="p-5 overflow-y-auto flex-1">
          {error && (
            <Alert variant="error" className="mb-4">
              {error}
            </Alert>
          )}

          {step === 'pick' && (
            <div className="space-y-4">
              <p className="text-sm text-text-muted">
                Drop an old MoSPI bulletin (PDF) to reverse-engineer its layout
                into a reusable AST template. The system will detect headings,
                tables, paragraphs, and charts, then build a block skeleton you
                can attach to any completed analysis.
              </p>
              <div>
                <label className="text-xs font-medium text-text mb-1 block">
                  Template name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. PLFS Quarterly Bulletin Q4"
                  className="w-full rounded-lg border border-border px-3 py-2 text-sm bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-text mb-1 block">
                  Source PDF
                </label>
                <label
                  htmlFor="tpl-pdf"
                  className="block rounded-xl border-2 border-dashed border-border hover:border-accent/50 p-6 cursor-pointer text-center transition-colors"
                >
                  <FileUp className="h-8 w-8 mx-auto text-text-muted mb-2" />
                  <p className="text-sm font-medium text-text">
                    {file ? file.name : 'Click to choose a PDF'}
                  </p>
                  <p className="text-xs text-text-muted mt-1">
                    Only PDF files are accepted. Datasets (CSV/XLSX) go through
                    the Upload page.
                  </p>
                </label>
                <input
                  id="tpl-pdf"
                  type="file"
                  accept="application/pdf,.pdf"
                  className="hidden"
                  onChange={(e) => onPick(e.target.files?.[0] || null)}
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="secondary" onClick={onClose}>
                  Cancel
                </Button>
                <Button onClick={upload} disabled={!file || !name.trim()}>
                  <Sparkles className="h-4 w-4 mr-1" /> Extract AST
                </Button>
              </div>
            </div>
          )}

          {step === 'uploading' && (
            <div className="py-8 text-center">
              <Loader2 className="h-6 w-6 animate-spin mx-auto text-primary mb-3" />
              <p className="text-sm">
                Hashing PDF · running vision-spatial extraction · compiling AST…
              </p>
            </div>
          )}

          {step === 'preview' && extractedAst && (
            <div className="space-y-4">
              <div className="rounded-lg border border-success/30 bg-success/5 p-3 text-sm">
                <div className="flex items-center gap-2 text-success font-medium mb-1">
                  <CheckCircle2 className="h-4 w-4" /> Template extracted
                </div>
                <div className="grid grid-cols-2 gap-1 text-xs text-text-muted">
                  <div>
                    <span className="font-medium text-text">Name:</span>{' '}
                    {extractedAst.name}
                  </div>
                  <div>
                    <span className="font-medium text-text">Pages:</span>{' '}
                    {extractedAst.page_count ?? '—'}
                  </div>
                  <div>
                    <span className="font-medium text-text">Method:</span>{' '}
                    {extractedAst.extraction_method ?? '—'}
                  </div>
                  <div>
                    <span className="font-medium text-text">Blocks:</span>{' '}
                    {extractedAst.ast?.blocks?.length || 0}
                  </div>
                  <div className="col-span-2 font-mono truncate">
                    <span className="font-medium text-text font-sans">Hash:</span>{' '}
                    {extractedAst.source_hash?.slice(0, 32)}…
                  </div>
                </div>
              </div>

              <div className="border border-border rounded-lg overflow-hidden">
                <div className="bg-surface px-3 py-2 text-xs font-semibold text-text-muted border-b border-border">
                  Detected blocks
                </div>
                <div className="max-h-64 overflow-y-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-surface sticky top-0">
                      <tr className="text-left text-text-muted">
                        <th className="px-3 py-1.5">Kind</th>
                        <th className="px-3 py-1.5">Section</th>
                        <th className="px-3 py-1.5">Title</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(extractedAst.ast?.blocks || []).map((b, i) => (
                        <tr key={i} className="border-t border-border/40">
                          <td className="px-3 py-1.5">
                            <Badge variant="muted">{String(b.kind || '')}</Badge>
                          </td>
                          <td className="px-3 py-1.5 text-text-muted">
                            {String(b.section || '')}
                          </td>
                          <td className="px-3 py-1.5">{String(b.title || '')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="flex justify-end gap-2">
                <Button variant="secondary" onClick={onClose}>
                  Keep template, close
                </Button>
                <Button onClick={generate}>
                  Generate report with this template →
                </Button>
              </div>
            </div>
          )}

          {step === 'generating' && (
            <div className="py-8 text-center">
              <Loader2 className="h-6 w-6 animate-spin mx-auto text-primary mb-3" />
              <p className="text-sm">
                Queuing new report job · running Phases 1-6 with the extracted
                template…
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------- Draggable proposal card ----------------

function DraggableProposal({
  block,
  onInsert,
}: {
  block: RenderedBlock;
  onInsert?: () => void | Promise<void>;
}) {
  const [inserting, setInserting] = useState(false);

  const onDragStart = (e: React.DragEvent) => {
    writeDragPayload(e.dataTransfer, block, false);
    e.dataTransfer.effectAllowed = 'copy';
  };

  const insert = async () => {
    if (!onInsert || inserting) return;
    setInserting(true);
    try {
      await onInsert();
    } finally {
      setInserting(false);
    }
  };

  return (
    <div
      draggable
      onDragStart={onDragStart}
      className="rounded-lg border border-dashed border-accent/40 bg-accent/5 p-2 cursor-grab active:cursor-grabbing"
      title="Drag into BI Findings or any section drop zone"
    >
      <div className="flex items-center gap-2 mb-1">
        <GripVertical className="h-3 w-3 text-text-muted" />
        <span className="text-[11px] font-semibold text-primary uppercase tracking-wide">
          Drag to insert
        </span>
        <Badge variant="muted">{block.kind}</Badge>
        <span className="text-[10px] text-text-muted truncate">{block.title}</span>
      </div>
      <div className="text-xs pointer-events-none">
        <BlockBody block={block} editing={false} draft="" setDraft={() => {}} />
      </div>
      {onInsert && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="mt-2 w-full pointer-events-auto"
          disabled={inserting}
          onClick={insert}
        >
          {inserting ? (
            <Loader2 className="h-3 w-3 animate-spin mr-1" />
          ) : null}
          Insert into BI Findings
        </Button>
      )}
    </div>
  );
}
