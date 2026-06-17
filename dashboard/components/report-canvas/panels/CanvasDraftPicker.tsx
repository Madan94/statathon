'use client';

import { useEffect, useMemo, useState } from 'react';
import { Clock, Copy, FilePlus2, Loader2, SortAsc } from 'lucide-react';
import { generatePhaseApi, type CanvasDraftSummary } from '@/lib/api';

interface Props {
  templateId: string;
  signature: string;
  open: boolean;
  currentDraftId?: string | null;
  onSelect: (draft: CanvasDraftSummary) => void;
  onClose?: () => void;
}

type SortMode = 'updated_desc' | 'updated_asc' | 'created_desc' | 'created_asc' | 'name_asc';

function fmt(ts?: string | null): string {
  if (!ts) return 'Never saved';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
}

export function CanvasDraftPicker({ templateId, signature, open, currentDraftId, onSelect, onClose }: Props) {
  const [sort, setSort] = useState<SortMode>('updated_desc');
  const [drafts, setDrafts] = useState<CanvasDraftSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [committing, setCommitting] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [namedDraftsAvailable, setNamedDraftsAvailable] = useState(true);

  const defaultName = useMemo(() => {
    const now = new Date();
    return `Draft ${now.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })} ${now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}`;
  }, []);

  const load = async (nextSort = sort) => {
    setLoading(true);
    setError('');
    try {
      const res = await generatePhaseApi.listCanvasDrafts(templateId, signature, nextSort);
      setNamedDraftsAvailable(true);
      setDrafts(res.drafts || []);
      if (!currentDraftId && res.drafts?.length === 1) {
        // Keep the picker open; the officer still explicitly selects or creates.
      }
    } catch {
      setNamedDraftsAvailable(false);
      try {
        const layout = await generatePhaseApi.getCanvasLayout(templateId, signature);
        setDrafts([{
          draftId: '__legacy__',
          name: 'Default draft (legacy autosave)',
          createdAt: null,
          updatedAt: layout.updatedAt,
          blockCount: Object.keys(layout.blocks || {}).length,
          pageCount: layout.pages?.length || 0,
        }]);
      } catch {
        setDrafts([{ draftId: '__legacy__', name: 'Default draft (legacy autosave)', createdAt: null, updatedAt: null, blockCount: 0, pageCount: 0 }]);
      }
      setError('Named draft API is not available on the running backend yet. Select the legacy draft, or restart the backend to enable named drafts.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) void load(sort);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, templateId, signature, sort]);

  const create = async () => {
    const finalName = (name || defaultName).trim();
    if (!finalName) return;
    setCreating(true);
    setError('');
    if (!namedDraftsAvailable) {
      const fallback = drafts.find(d => d.draftId === '__legacy__') || { draftId: '__legacy__', name: 'Default draft (legacy autosave)', createdAt: null, updatedAt: null, blockCount: 0, pageCount: 0 };
      onSelect({ ...fallback, name: `${finalName} (legacy autosave)` });
      setCreating(false);
      return;
    }
    try {
      const draft = await generatePhaseApi.createCanvasDraft(templateId, signature, { name: finalName, cloneFrom: currentDraftId && currentDraftId !== '__legacy__' ? currentDraftId : undefined });
      setName('');
      onSelect(draft);
    } catch (err) {
      const fallback = drafts.find(d => d.draftId === '__legacy__');
      if (fallback) {
        setNamedDraftsAvailable(false);
        onSelect({ ...fallback, name: `${finalName} (legacy autosave)` });
      } else {
        setError(err instanceof Error ? err.message : 'Failed to create draft');
      }
    } finally {
      setCreating(false);
    }
  };

  const commitDraft = async (draftId: string) => {
    setCommitting(draftId);
    setError('');
    setNotice('');
    try {
      const result = await generatePhaseApi.commitCanvasDraftToReport(templateId, signature, draftId);
      setNotice(`Committed to official report v${result.version}: ${result.sectionsAdded} sections, ${result.blocksCommitted + result.tablesCommitted + result.chartsCommitted} blocks.`);
      void load(sort);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Commit endpoint unavailable. Restart backend to enable official report commit.');
    } finally {
      setCommitting(null);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-900/45 p-4 backdrop-blur-sm">
      <div className="w-full max-w-2xl overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Choose report canvas draft</h2>
            <p className="text-xs text-slate-500">Select an existing draft or name a new one before editing. Autosave keeps the latest hand edits, resizing, order and generated sections.</p>
          </div>
          {onClose && <button onClick={onClose} className="rounded px-2 py-1 text-xs text-slate-500 hover:bg-slate-100">Close</button>}
        </div>

        <div className="space-y-4 p-5">
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3">
            <div className="flex items-center gap-2 text-xs font-semibold text-emerald-800"><FilePlus2 className="h-4 w-4" /> Create new draft</div>
            <div className="mt-2 flex gap-2">
              <input value={name} onChange={e => setName(e.target.value)} placeholder={defaultName} className="min-w-0 flex-1 rounded border border-emerald-200 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500" />
              <button onClick={create} disabled={creating} className="rounded bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-700 disabled:bg-slate-300">
                {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : namedDraftsAvailable ? 'Create' : 'Use legacy'}
              </button>
            </div>
            {currentDraftId && <p className="mt-1 text-[11px] text-emerald-700">{namedDraftsAvailable ? 'New draft will clone the currently selected draft.' : 'Backend restart is needed for true named drafts; this will continue in the legacy autosave draft.'}</p>}
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500"><Copy className="h-3.5 w-3.5" /> Existing drafts</div>
            <label className="flex items-center gap-1 text-xs text-slate-500"><SortAsc className="h-3.5 w-3.5" />
              <select value={sort} onChange={e => setSort(e.target.value as SortMode)} className="rounded border border-slate-200 bg-white px-2 py-1 text-xs">
                <option value="updated_desc">Last edited first</option>
                <option value="updated_asc">Last edited last</option>
                <option value="created_desc">Newest first</option>
                <option value="created_asc">Oldest first</option>
                <option value="name_asc">Name A-Z</option>
              </select>
            </label>
          </div>

          {error && <p className="rounded bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
          {notice && <p className="rounded bg-emerald-50 px-3 py-2 text-xs text-emerald-700">{notice}</p>}
          {loading ? (
            <div className="flex items-center justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-slate-300" /></div>
          ) : (
            <div className="max-h-80 space-y-2 overflow-auto">
              {drafts.map(draft => (
                <div key={draft.draftId} className={`rounded-lg border px-4 py-3 transition-colors ${currentDraftId === draft.draftId ? 'border-blue-300 bg-blue-50 shadow-sm' : 'border-slate-200 hover:border-blue-200 hover:bg-slate-50'}`}>
                  <button onClick={() => onSelect(draft)} className="flex w-full items-center justify-between text-left">
                  <div>
                    <p className="text-sm font-semibold text-slate-800">{draft.name}</p>
                    <p className="mt-0.5 flex items-center gap-1 text-[11px] text-slate-500"><Clock className="h-3 w-3" /> Last edited {fmt(draft.updatedAt)}</p>
                  </div>
                  <div className="rounded-md bg-slate-50 px-2 py-1 text-right text-[11px] text-slate-500">
                    <div className="font-medium text-slate-700">{draft.blockCount} blocks</div>
                    <div>{draft.pageCount || 0} pages</div>
                  </div>
                  </button>
                  <div className="mt-2 flex items-center justify-end gap-2 border-t border-slate-100 pt-2">
                    <button onClick={() => commitDraft(draft.draftId)} disabled={committing === draft.draftId}
                      className="rounded border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40">
                      {committing === draft.draftId ? 'Committing…' : 'Commit to official report'}
                    </button>
                  </div>
                </div>
              ))}
              {!drafts.length && <p className="rounded border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-500">No drafts yet. Create one to start editing.</p>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
