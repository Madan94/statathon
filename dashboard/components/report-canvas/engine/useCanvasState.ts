'use client';
import { useCallback, useRef, useState } from 'react';
import { generatePhaseApi } from '@/lib/api';

/* ═══════════════════════════════════════════════════════════════════
   Canvas State — central state for the entire report canvas.
   ═══════════════════════════════════════════════════════════════════ */

export interface PageBlock {
  id: string;
  index: number;
  kind: 'heading' | 'narrative' | 'table' | 'chart' | 'metric' | 'key_finding' | 'source_note' | 'divider';
  title: string;
  content: string;
  tableData?: Record<string, unknown>;
  metricValue?: string;
  metricUnit?: string;
  sectionPath: string[];
  status: 'pending' | 'generating' | 'done' | 'error';
  pageIndex: number; // which page this block lives on
}

export interface CanvasPage {
  id: string;
  index: number;
  blocks: string[]; // block IDs on this page
}

export type Phase = 'init' | 'ready' | 'generating' | 'paused' | 'complete';
export type Panel = 'left' | 'right' | null;

export interface QueueItem {
  index: number;
  plan_id: string;
  question_id: string;
  component_type: string;
  title: string;
  section_path: string[];
  status: string;
}

export function useCanvasState(templateId: string, signature: string) {
  const [phase, setPhase] = useState<Phase>('init');
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [blocks, setBlocks] = useState<Map<string, PageBlock>>(new Map());
  const [pages, setPages] = useState<CanvasPage[]>([{ id: 'page-1', index: 0, blocks: [] }]);
  const [currentPage, setCurrentPage] = useState(0);
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel>(null);
  const [generating, setGenerating] = useState(false);

  const togglePanel = useCallback((p: Panel) => {
    setPanel(prev => prev === p ? null : p);
  }, []);

  const addPage = useCallback(() => {
    setPages(prev => {
      const newPage: CanvasPage = { id: `page-${prev.length + 1}`, index: prev.length, blocks: [] };
      return [...prev, newPage];
    });
  }, []);

  const goToPage = useCallback((idx: number) => {
    setCurrentPage(Math.max(0, Math.min(idx, pages.length - 1)));
  }, [pages.length]);

  const nextPage = useCallback(() => goToPage(currentPage + 1), [currentPage, goToPage]);
  const prevPage = useCallback(() => goToPage(currentPage - 1), [currentPage, goToPage]);

  const addBlockToPage = useCallback((block: PageBlock, pageIdx?: number) => {
    const targetPage = pageIdx ?? currentPage;
    setBlocks(prev => new Map(prev).set(block.id, { ...block, pageIndex: targetPage }));
    setPages(prev => prev.map((p, i) => i === targetPage ? { ...p, blocks: [...p.blocks, block.id] } : p));
  }, [currentPage]);

  const updateBlock = useCallback((id: string, updates: Partial<PageBlock>) => {
    setBlocks(prev => {
      const m = new Map(prev);
      const existing = m.get(id);
      if (existing) m.set(id, { ...existing, ...updates });
      return m;
    });
  }, []);

  const removeBlock = useCallback((id: string) => {
    setBlocks(prev => { const m = new Map(prev); m.delete(id); return m; });
    setPages(prev => prev.map(p => ({ ...p, blocks: p.blocks.filter(bid => bid !== id) })));
  }, []);

  const getPageBlocks = useCallback((pageIdx: number): PageBlock[] => {
    const page = pages[pageIdx];
    if (!page) return [];
    return page.blocks.map(id => blocks.get(id)).filter(Boolean) as PageBlock[];
  }, [pages, blocks]);

  const currentPageBlocks = getPageBlocks(currentPage);
  const selectedBlock = selectedBlockId ? blocks.get(selectedBlockId) || null : null;
  const totalBlocks = blocks.size;
  const doneBlocks = Array.from(blocks.values()).filter(b => b.status === 'done').length;
  const progress = totalBlocks > 0 ? Math.round((doneBlocks / totalBlocks) * 100) : 0;

  return {
    phase, setPhase, queue, setQueue, blocks, pages, currentPage, selectedBlockId,
    panel, generating, setGenerating, togglePanel, addPage, goToPage, nextPage, prevPage,
    addBlockToPage, updateBlock, removeBlock, getPageBlocks, currentPageBlocks,
    selectedBlock, setSelectedBlockId, totalBlocks, doneBlocks, progress, setPages, setBlocks,
  };
}
