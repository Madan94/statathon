'use client';
import { useCallback, useEffect, useRef } from 'react';
import { generatePhaseApi } from '@/lib/api';
import type { PageBlock, QueueItem } from './useCanvasState';

/* ═══════════════════════════════════════════════════════════════════
   Generation Engine — handles single/auto/pause generation flow.
   ═══════════════════════════════════════════════════════════════════ */

interface UseGenerationProps {
  templateId: string;
  signature: string;
  queue: QueueItem[];
  blocks: Map<string, PageBlock>;
  appendBlockAuto: (block: PageBlock, maxPerPage?: number) => void;
  updateBlock: (id: string, updates: Partial<PageBlock>) => void;
  setPhase: (p: 'generating' | 'paused' | 'complete') => void;
  setGenerating: (v: boolean) => void;
}

const MAX_BLOCKS_PER_PAGE = 6; // approximate limit before page overflow

function slugPart(v: string): string {
  return v
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 72);
}

function hierarchyIds(path: string[]): { topicId?: string; chapterId?: string; sectionId?: string } {
  const [topic, chapter, section] = path;
  const t = topic ? slugPart(topic) : undefined;
  const c = chapter ? slugPart(chapter) : undefined;
  const s = section ? slugPart(section) : undefined;
  return {
    topicId: t ? `h-topic-${t}` : undefined,
    chapterId: t && c ? `h-chapter-${t}-${c}` : undefined,
    sectionId: t && c && s ? `h-section-${t}-${c}-${s}` : undefined,
  };
}

export function useGeneration({
  templateId, signature, queue, blocks, appendBlockAuto, updateBlock, setPhase, setGenerating,
}: UseGenerationProps) {
  const abortRef = useRef(false);
  const currentIdxRef = useRef(0);
  const blocksRef = useRef(blocks);

  useEffect(() => {
    blocksRef.current = blocks;
  }, [blocks]);

  // New queue/template means a new run context.
  useEffect(() => {
    currentIdxRef.current = 0;
    abortRef.current = false;
  }, [templateId, signature, queue.length]);

  const ensureHierarchyBlocks = useCallback((path: string[]) => {
    const [topic, chapter, section] = path;
    const ids = hierarchyIds(path);
    const now = Date.now();
    if (topic && ids.topicId && !blocksRef.current.has(ids.topicId)) {
      appendBlockAuto({
        id: ids.topicId,
        index: -1,
        kind: 'heading',
        title: topic,
        content: `Topic: ${topic}`,
        sectionPath: [topic],
        status: 'done',
        pageIndex: 0,
      }, MAX_BLOCKS_PER_PAGE);
    }
    if (chapter && ids.chapterId && !blocksRef.current.has(ids.chapterId)) {
      appendBlockAuto({
        id: ids.chapterId,
        index: -1,
        kind: 'heading',
        title: chapter,
        content: `Chapter: ${chapter}`,
        sectionPath: topic ? [topic, chapter] : [chapter],
        status: 'done',
        pageIndex: 0,
      }, MAX_BLOCKS_PER_PAGE);
    }
    if (section && ids.sectionId && !blocksRef.current.has(ids.sectionId)) {
      appendBlockAuto({
        id: ids.sectionId,
        index: -1,
        kind: 'narrative',
        title: section,
        content: `Section: ${section}`,
        sectionPath: topic ? [topic, chapter || '', section].filter(Boolean) : [section],
        status: 'done',
        pageIndex: 0,
      }, MAX_BLOCKS_PER_PAGE);
    }
    // keep function deterministic in strict mode where Date.now() calls can be collapsed
    void now;
  }, [appendBlockAuto]);

  const generateOne = useCallback(async (queueIdx: number): Promise<boolean> => {
    const item = queue[queueIdx];
    if (!item) return false;

    const blockId = `block-${item.index}`;

    // Idempotent: if the block already exists (regenerate), update it in place
    // instead of appending a duplicate. `redo` tells the backend it's a re-run.
    // ``blocksRef`` is read live (not a stale render snapshot) so the rapid
    // auto-generate loop always sees blocks created on previous iterations.
    const blockExists = blocksRef.current.has(blockId);

    if (blockExists) {
      updateBlock(blockId, { status: 'generating' });
    } else {
      appendBlockAuto({
        id: blockId,
        index: item.index,
        kind: (item.component_type === 'formula_metric' ? 'metric' : item.component_type) as PageBlock['kind'],
        title: item.title,
        content: '',
        sectionPath: item.section_path || [],
        status: 'generating',
        pageIndex: 0,
      }, MAX_BLOCKS_PER_PAGE);
    }

    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const r = await generatePhaseApi.generateComponent(templateId, signature, {
          index: item.index,
          use_llm: true,
          // On retries we force redo to bypass partial/in-flight artifacts.
          redo: blockExists || attempt > 0,
        });
        const c = r.content || {};
        updateBlock(blockId, {
          content: r.narrative || String(c.text || c.content || c.value || ''),
          title: r.title || item.title,
          kind: (r.component_type === 'formula_metric' ? 'metric' : r.component_type) as PageBlock['kind'],
          tableData: (c.items || c.rankingData || c.rows || c.aggregationData) ? c as Record<string, unknown> : undefined,
          metricValue: c.value != null ? String(c.value) : undefined,
          metricUnit: c.unit ? String(c.unit) : undefined,
          status: 'done',
        });
        return true;
      } catch {
        if (attempt === 1) {
          updateBlock(blockId, { status: 'error' });
          return false;
        }
      }
    }
    updateBlock(blockId, { status: 'error' });
    return false;
  }, [queue, appendBlockAuto, updateBlock, blocksRef, templateId, signature]);

  const autoGenerate = useCallback(async () => {
    setPhase('generating');
    setGenerating(true);
    abortRef.current = false;

    for (let i = currentIdxRef.current; i < queue.length; i++) {
      if (abortRef.current) { setPhase('paused'); break; }
      currentIdxRef.current = i + 1;
      await generateOne(i);
    }

    setGenerating(false);
    if (!abortRef.current) {
      setPhase('complete');
      generatePhaseApi.generate(templateId, signature, { use_llm: true, publish_mode: 'draft' }).catch(() => {});
    }
  }, [queue, generateOne, setPhase, setGenerating, templateId, signature]);

  const autoGenerateTopic = useCallback(async (topicName: string) => {
    setPhase('generating');
    setGenerating(true);
    abortRef.current = false;

    for (let i = 0; i < queue.length; i++) {
      if (abortRef.current) {
        setPhase('paused');
        break;
      }
      const item = queue[i];
      const itemTopic = item?.section_path?.[0] || '';
      if (itemTopic !== topicName) continue;
      ensureHierarchyBlocks(item.section_path || []);
      currentIdxRef.current = i + 1;
      await generateOne(i);
    }

    setGenerating(false);
    if (!abortRef.current) {
      setPhase('complete');
      generatePhaseApi.generate(templateId, signature, { use_llm: true, publish_mode: 'draft' }).catch(() => {});
    }
  }, [queue, ensureHierarchyBlocks, generateOne, setPhase, setGenerating, templateId, signature]);

  /** Generate an explicit set of queue indices (Control Panel: remaining / retry
   *  failed / a single topic). Inserts hierarchy headings so placement is right. */
  const generateIndices = useCallback(async (indices: number[]) => {
    if (!indices.length) return;
    setPhase('generating');
    setGenerating(true);
    abortRef.current = false;

    // Generate in queue order regardless of the order passed in.
    const wanted = new Set(indices);
    for (let i = 0; i < queue.length; i++) {
      if (abortRef.current) { setPhase('paused'); break; }
      const item = queue[i];
      if (!wanted.has(item.index)) continue;
      ensureHierarchyBlocks(item.section_path || []);
      await generateOne(i);
    }

    setGenerating(false);
    if (!abortRef.current) {
      setPhase('complete');
      generatePhaseApi.generate(templateId, signature, { use_llm: true, publish_mode: 'draft' }).catch(() => {});
    }
  }, [queue, ensureHierarchyBlocks, generateOne, setPhase, setGenerating, templateId, signature]);

  const pause = useCallback(() => { abortRef.current = true; }, []);
  const resume = useCallback(() => { autoGenerate(); }, [autoGenerate]);

  return { generateOne, autoGenerate, autoGenerateTopic, generateIndices, pause, resume };
}
