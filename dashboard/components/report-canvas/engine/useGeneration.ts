'use client';
import { useCallback, useRef } from 'react';
import { generatePhaseApi } from '@/lib/api';
import type { PageBlock, QueueItem } from './useCanvasState';

/* ═══════════════════════════════════════════════════════════════════
   Generation Engine — handles single/auto/pause generation flow.
   ═══════════════════════════════════════════════════════════════════ */

interface UseGenerationProps {
  templateId: string;
  signature: string;
  queue: QueueItem[];
  addBlockToPage: (block: PageBlock, pageIdx?: number) => void;
  updateBlock: (id: string, updates: Partial<PageBlock>) => void;
  pages: { blocks: string[] }[];
  addPage: () => void;
  setPhase: (p: 'generating' | 'paused' | 'complete') => void;
  setGenerating: (v: boolean) => void;
}

const MAX_BLOCKS_PER_PAGE = 6; // approximate limit before page overflow

export function useGeneration({
  templateId, signature, queue, addBlockToPage, updateBlock,
  pages, addPage, setPhase, setGenerating,
}: UseGenerationProps) {
  const abortRef = useRef(false);
  const currentIdxRef = useRef(0);

  const generateOne = useCallback(async (queueIdx: number): Promise<boolean> => {
    const item = queue[queueIdx];
    if (!item) return false;

    const blockId = `block-${item.index}`;

    // Determine which page to put this on
    let targetPage = pages.length - 1;
    if (pages[targetPage]?.blocks.length >= MAX_BLOCKS_PER_PAGE) {
      addPage();
      targetPage = pages.length; // will be the new page
    }

    // Add as generating
    const newBlock: PageBlock = {
      id: blockId,
      index: item.index,
      kind: (item.component_type === 'formula_metric' ? 'metric' : item.component_type) as PageBlock['kind'],
      title: item.title,
      content: '',
      sectionPath: item.section_path || [],
      status: 'generating',
      pageIndex: targetPage,
    };
    addBlockToPage(newBlock, targetPage);

    try {
      const r = await generatePhaseApi.generateComponent(templateId, signature, {
        index: item.index, use_llm: true, redo: false,
      });
      const c = r.content || {};
      updateBlock(blockId, {
        content: r.narrative || String(c.text || c.content || c.value || ''),
        title: r.title || item.title,
        kind: (r.component_type === 'formula_metric' ? 'metric' : r.component_type) as PageBlock['kind'],
        tableData: (c.items || c.rankingData || c.rows) ? c as Record<string, unknown> : undefined,
        metricValue: c.value != null ? String(c.value) : undefined,
        metricUnit: c.unit ? String(c.unit) : undefined,
        status: 'done',
      });
      return true;
    } catch {
      updateBlock(blockId, { status: 'error' });
      return false;
    }
  }, [queue, pages, addPage, addBlockToPage, updateBlock, templateId, signature]);

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

  const pause = useCallback(() => { abortRef.current = true; }, []);
  const resume = useCallback(() => { autoGenerate(); }, [autoGenerate]);

  return { generateOne, autoGenerate, pause, resume };
}
