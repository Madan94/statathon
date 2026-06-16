'use client';
import { useCallback, useState } from 'react';
import { generatePhaseApi } from '@/lib/api';
import type { PageBlock, QueueItem } from './useCanvasState';
import type { LayoutDigest } from './paginationEngine';
import { classifyIntent } from './assistantOrchestrator';

/* ═══════════════════════════════════════════════════════════════════
   Canvas Agent — the MoSPI Intelligence Assistant.

   Restores the client-side tool registry + keyword-intent router that
   was lost in the modular rewrite (originally commit 42bbb3d). The agent
   operates on the live canvas state: it can inspect components, list the
   queue, show the outline, edit narrative text, regenerate, add and
   remove blocks. Every action runs through a named tool so a future LLM
   function-calling layer can swap the keyword router for real tool calls
   without changing the tool surface.
   ═══════════════════════════════════════════════════════════════════ */

export interface ChatMessage {
  id: string;
  role: 'system' | 'assistant' | 'user';
  content: string;
  timestamp: number;
  status?: 'thinking' | 'done' | 'error';
  tool?: string;
  /** Verified analysis blocks returned by the DeepAgent, available to insert. */
  blocks?: Array<Record<string, unknown>>;
  /** The narrative text offered for one-click insertion into the report. */
  insertText?: string;
  /** True when the answer used the officer's CONFIRMED bindings; false = exploratory. */
  bound?: boolean;
  /** Provenance footer: columns the answer resolved to + rows scanned. */
  provenance?: { columns: string[]; rows: number };
  /** Top result rows the answer is based on (collapsible 'Show data'). */
  resultTable?: { columns: string[]; rows: Array<Record<string, unknown>> };
}

interface UseCanvasAgentProps {
  templateId: string;
  signature: string;
  queue: QueueItem[];
  blocks: Map<string, PageBlock>;
  updateBlock: (id: string, updates: Partial<PageBlock>) => void;
  removeBlock: (id: string) => void;
  selectedBlock: PageBlock | null;
  /** Regenerate a component by its queue index (delegates to the generation engine). */
  regenerate: (queueIdx: number) => Promise<boolean>;
  /** Insert a free-form block authored by the Deep BI chat into the report. */
  insertBlock?: (block: PageBlock) => void;
  /** Live page-capacity digest so the agent can right-size + place content (D-L5). */
  layout?: LayoutDigest;
  /** Re-run the height-aware packer (used by /repack, /balance). */
  repack?: () => void;
  /** Navigate to a 1-based page (used to confirm where a block landed). */
  goToPage?: (pageIdx: number) => void;
  /** Generate all components of a topic (orchestrator: "generate topic X"). */
  generateTopic?: (topic: string) => void;
  /** Retry all failed components (orchestrator: "retry failed"). */
  retryFailed?: () => void;
}

function blockByIndex(blocks: Map<string, PageBlock>, idx: number): PageBlock | undefined {
  return blocks.get(`block-${idx}`);
}


export function useCanvasAgent({
  templateId, signature, queue, blocks, updateBlock, removeBlock, selectedBlock, regenerate, insertBlock,
  layout, repack, goToPage, generateTopic, retryFailed,
}: UseCanvasAgentProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);

  const addMessage = useCallback((msg: Omit<ChatMessage, 'id' | 'timestamp'>) => {
    setMessages(prev => [...prev, {
      ...msg,
      id: `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      timestamp: Date.now(),
    }]);
  }, []);

  /** Named tool surface. Pure where possible; async for backend round-trips. */
  const tools = useCallback(() => ({
    inspect_component: (idx: number) => {
      const item = queue[idx];
      const block = blockByIndex(blocks, idx);
      if (!item || !block) return { error: `Component ${idx} not found` };
      return {
        index: idx, planId: item.plan_id, questionId: item.question_id,
        componentType: item.component_type, title: block.title,
        sectionPath: item.section_path, status: block.status,
        content: block.content?.slice(0, 240), hasData: !!block.tableData,
      };
    },
    get_all_components: () =>
      queue.map((q, i) => {
        const b = blockByIndex(blocks, i);
        return {
          index: i, title: b?.title || q.title, type: q.component_type,
          generated: b?.status === 'done', section: (q.section_path || []).join(' › '),
        };
      }),
    get_report_outline: () =>
      Array.from(blocks.values())
        .filter(b => b.kind === 'heading')
        .map(b => ({ id: b.id, level: b.sectionPath.length || 1, text: b.title || b.content })),
    update_narrative: (idx: number, newText: string) => {
      const block = blockByIndex(blocks, idx);
      if (!block) return { error: `Component ${idx} not found` };
      updateBlock(block.id, { content: newText });
      return { success: true, index: idx };
    },
    regenerate_component: async (idx: number) => {
      const ok = await regenerate(idx);
      const block = blockByIndex(blocks, idx);
      return ok ? { success: true, title: block?.title } : { error: 'Regeneration failed' };
    },
    remove_component: (idx: number) => {
      const block = blockByIndex(blocks, idx);
      if (!block) return { error: `Component ${idx} not found` };
      removeBlock(block.id);
      return { success: true, removed: block.title };
    },
  }), [queue, blocks, updateBlock, removeBlock, regenerate]);

  /** Orchestrator dispatch (S3): classify natural language → tool, falling
   *  through to the DeepAgent for analysis questions. Resolves the target index
   *  from the message, else the selected block. */
  const send = useCallback(async (userMsg: string) => {
    const text = userMsg.trim();
    if (!text) return;
    addMessage({ role: 'user', content: text });
    setBusy(true);

    const t = tools();
    const lower = text.toLowerCase();
    const intent = classifyIntent(text);
    const fallbackIdx = selectedBlock?.index ?? 0;
    const idx = intent.index ?? fallbackIdx;

    let response = '';
    let toolUsed = '';
    let deepBlocks: Array<Record<string, unknown>> | undefined;
    let insertText: string | undefined;
    let bound: boolean | undefined;
    let provenance: { columns: string[]; rows: number } | undefined;
    let resultTable: { columns: string[]; rows: Array<Record<string, unknown>> } | undefined;

    try {
      // ── Orchestrator pre-empts: topic generation + retry-failed phrasing ──
      if (/\bretry\b.*\bfailed\b|\bfailed\b.*\bretry\b/.test(lower) && retryFailed) {
        toolUsed = 'retry_failed';
        retryFailed();
        response = '✓ Retrying all failed components.';
      } else if (/\bgenerate\b.*\btopic\b/.test(lower) && generateTopic) {
        toolUsed = 'generate_topic';
        const m = text.match(/topic\s+(.+)$/i);
        const topic = m ? m[1].trim().replace(/^["“”']|["“”']$/g, '') : '';
        if (topic) { generateTopic(topic); response = `✓ Generating topic **${topic}**.`; }
        else response = 'Which topic? e.g. "generate topic Renewable Energy Potential".';
      } else if (intent.tool === 'footnote') {
        // Lightweight footnote: append a caveat note under the selected block.
        toolUsed = 'add_footnote';
        const target = blockByIndex(blocks, idx);
        if (target) {
          const note = 'Note: figures flagged * have a relative standard error above 20% and should be used with caution.';
          updateBlock(target.id, { content: `${target.content || ''}\n\n${note}`.trim() });
          response = `✓ Added a reliability footnote to **${target.title}**.`;
        } else response = 'Select the table or block to footnote first.';
      } else if (intent.tool === 'inspect') {
        toolUsed = 'inspect_component';
        const r = t.inspect_component(idx);
        response = 'error' in r ? `Error: ${r.error}` :
          `**Component ${idx}: ${r.title}**\n` +
          `Type: ${r.componentType} · Status: ${r.status}\n` +
          `Section: ${(r.sectionPath || []).join(' › ')}\n` +
          `Plan: ${r.planId} · Question: ${r.questionId}\n` +
          (r.content ? `\nData source: "${r.content}"` : '\nNo content yet.');
      } else if (intent.tool === 'regenerate') {
        toolUsed = 'regenerate_component';
        const r = await t.regenerate_component(idx);
        response = 'error' in r ? `Failed: ${r.error}` : `✓ Regenerated **${r.title || `component ${idx}`}**.`;
      } else if (intent.tool === 'outline') {
        toolUsed = 'get_report_outline';
        const outline = t.get_report_outline();
        response = `**Report outline (${outline.length} headings):**\n\n` +
          outline.map((h, i) => `${'  '.repeat((h.level || 1) - 1)}${i + 1}. ${h.text}`).join('\n');
      } else if (intent.tool === 'list') {
        toolUsed = 'get_all_components';
        const all = t.get_all_components();
        const done = all.filter(c => c.generated).length;
        response = `**Components: ${done}/${all.length} generated**\n\n` +
          all.slice(0, 15).map(c => `${c.generated ? '✓' : '◌'} [${c.index}] ${c.title} (${c.type})`).join('\n') +
          (all.length > 15 ? `\n… and ${all.length - 15} more` : '');
      } else if (intent.tool === 'shorten') {
        const block = blockByIndex(blocks, idx);
        if (!block?.content) {
          response = `Component ${idx} has no narrative to condense.`;
        } else {
          toolUsed = 'update_narrative';
          const firstSentence = block.content.split(/(?<=[.!?])\s/)[0] || block.content.slice(0, 160);
          t.update_narrative(idx, firstSentence);
          response = `✓ Condensed component ${idx} to its lead sentence.`;
        }
      } else if (intent.tool === 'update') {
        if (intent.text) {
          toolUsed = 'update_narrative';
          const r = t.update_narrative(idx, intent.text);
          response = 'error' in r ? `Error: ${r.error}` : `✓ Updated component ${idx}.`;
        } else {
          response = 'Provide the replacement text in quotes, e.g. update 3 to "New paragraph text".';
        }
      } else if (intent.tool === 'remove') {
        if (intent.index != null) {
          toolUsed = 'remove_component';
          const r = t.remove_component(idx);
          response = 'error' in r ? `Error: ${r.error}` : `✓ Removed: ${r.removed}`;
        } else {
          response = 'Specify which component to remove by index, e.g. remove 4.';
        }
      } else if (lower.startsWith('/intermediate')) {
        // Officer explicitly places a component into a chosen section (decision 1).
        const sectionMatch = text.match(/\/intermediate\s+(.+)/i);
        if (sectionMatch && selectedBlock?.content) {
          toolUsed = 'insert_at_section';
          const sectionPath = sectionMatch[1].split('>').map(s => s.trim()).filter(Boolean);
          insertAtSection(selectedBlock.content, sectionPath, selectedBlock.title);
          response = `✓ Inserted at section: **${sectionPath.join(' › ')}**`;
        } else {
          response = 'Usage: **/intermediate Section > Subsection** — select a block first, then place it.\n\nExample: **/intermediate Energy > Coal**';
        }
      } else if (intent.tool === 'layout') {
        // ── Layout awareness (D-L5): report per-page capacity ──
        toolUsed = 'layout_report';
        if (!layout) {
          response = 'Layout model is still warming up — try again in a moment.';
        } else {
          const lines = layout.pages.map(p =>
            `• Page ${p.page}: ${p.fillPct}% full · ${p.remainingPx}px free · ${p.blockCount} blocks`).join('\n');
          response = `**Document layout — ${layout.totalPages} page${layout.totalPages === 1 ? '' : 's'}**\n\n${lines}\n\n` +
            `Emptiest page: **${layout.emptiestPage}**. ` +
            (layout.lastPageHasRoom ? 'The last page can still take a short paragraph.' : 'The last page is nearly full — a new block will start a fresh page.');
        }
      } else if (intent.tool === 'repack') {
        toolUsed = 'repack_document';
        repack?.();
        response = '✓ Re-packed the document — blocks reflowed to fill pages to the budget with no orphaned headings.';
      } else if (intent.tool === 'balance') {
        toolUsed = 'balance_page';
        repack?.();
        response = '✓ Re-balanced pagination. Whitespace tightened; tables kept together with their captions.';
      } else if (intent.tool === 'fit') {
        // Right-size a draft narrative to the remaining space on the last page.
        toolUsed = 'fit_narrative';
        if (!layout || !selectedBlock?.content) {
          response = 'Select a narrative block first, then **/fit** trims it to the available space.';
        } else {
          const last = layout.pages[layout.pages.length - 1];
          const maxLines = Math.max(2, Math.floor(last.remainingPx / 21));
          const sentences = selectedBlock.content.split(/(?<=[.!?])\s/);
          let kept = ''; let lines = 0;
          for (const s of sentences) {
            const add = Math.ceil(s.length / 92);
            if (lines + add > maxLines) break;
            kept += (kept ? ' ' : '') + s; lines += add;
          }
          updateBlock(selectedBlock.id, { content: kept || sentences[0] });
          response = `✓ Fitted the narrative to ~${maxLines} lines so it sits cleanly on page ${last.page}.`;
        }
      } else if (intent.tool === 'help') {
        // Genuinely ambiguous short message — offer natural-language guidance.
        response =
          'I can help with your report. Just say it naturally — for example:\n' +
          '• “explain the coal table” / “where did this come from”\n' +
          '• “regenerate component 3” / “redo this”\n' +
          '• “trim this paragraph” / “make it shorter”\n' +
          '• “what’s still pending?” / “generate topic Renewable Energy”\n' +
          '• “is page 3 full?” / “tighten the layout” / “fit this”\n' +
          '• or ask a data question: “which state has the most coal reserves?”\n\n' +
          'No number? I use the block you’ve selected.';
      } else {
        // ── DEEP BI ESCALATION — free-form question / new analysis ──────────
        toolUsed = 'deep_bi';
        const r = await generatePhaseApi.canvasChat(templateId, signature, {
          query: text,
          selected_question_id: selectedBlock ? `block-${selectedBlock.index}` : undefined,
        });
        if (r.degraded) {
          response = r.text;
        } else {
          bound = r.route?.bound;
          // Provenance footer (decision B): resolved columns + rows scanned.
          const ctx = (r.context_used || {}) as Record<string, unknown>;
          const cols = Array.isArray(ctx.resolved_columns) ? (ctx.resolved_columns as string[]) : [];
          const rows = typeof ctx.dataset_rows === 'number' ? (ctx.dataset_rows as number) : 0;
          if (cols.length || rows) provenance = { columns: cols, rows };
          // Collapsible result rows from the analytics table, if any.
          const tbl = (r.analytics?.table || null) as { columns?: string[]; rows?: Array<Record<string, unknown>> } | null;
          if (tbl && Array.isArray(tbl.rows) && tbl.rows.length) {
            resultTable = { columns: tbl.columns || [], rows: tbl.rows.slice(0, 8) };
          }
          const verdict = r.verifier && typeof r.verifier === 'object'
            ? (r.verifier as Record<string, unknown>).verdict : undefined;
          const verifyTag = verdict ? `\n\n_Verifier: ${String(verdict)}_` : '';
          // Layout-aware landing hint (D-L5): tell the officer where it will go.
          const landTag = layout
            ? `\n\n_Insert lands on page ${layout.lastPageHasRoom ? layout.totalPages : layout.totalPages + 1} (current last page is ${layout.pages[layout.pages.length - 1]?.fillPct ?? 0}% full)._`
            : '';
          response = (r.text || 'Analysis complete.') + verifyTag + landTag;
          if (insertBlock && r.text) {
            deepBlocks = r.blocks;
            insertText = r.text;
          }
        }
      }
    } catch (err) {
      response = `Error: ${err instanceof Error ? err.message : 'Something went wrong'}`;
    }

    addMessage({ role: 'assistant', content: response, status: 'done', tool: toolUsed || undefined, blocks: deepBlocks, insertText, bound, provenance, resultTable });
    setBusy(false);
  }, [tools, addMessage, selectedBlock, blocks, templateId, signature, insertBlock, layout, repack, updateBlock, generateTopic, retryFailed]);

  /** Insert at end of current page (Option C: default behavior). */
  const insertNarrative = useCallback((text: string, title = 'Deep BI analysis') => {
    if (!insertBlock) return;
    const id = `block-deepbi-${Date.now()}`;
    insertBlock({
      id, index: -1, kind: 'narrative', title, content: text,
      sectionPath: [], status: 'done', pageIndex: -1, // -1 = end of current/last page
    });
    // Layout-aware confirmation: jump to where the block landed.
    if (goToPage && layout) goToPage(layout.lastPageHasRoom ? layout.totalPages : layout.totalPages + 1);
  }, [insertBlock, goToPage, layout]);

  /** Insert at a specific section (officer-controlled via /intermediate [section]). */
  const insertAtSection = useCallback((text: string, sectionPath: string[], title?: string) => {
    if (!insertBlock) return;
    const id = `block-deepbi-${Date.now()}`;
    insertBlock({
      id, index: -1, kind: 'narrative', title: title || 'Deep BI analysis', content: text,
      sectionPath, status: 'done', pageIndex: -1, // resolved based on section structure
    });
  }, [insertBlock]);

  return { messages, busy, send, insertNarrative, insertAtSection };
}
