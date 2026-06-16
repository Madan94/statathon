'use client';
import { useMemo } from 'react';
import type { PageBlock, QueueItem } from './useCanvasState';

/* ═══════════════════════════════════════════════════════════════════
   Bundle model (S2) — the honest progress truth for the report.

   The progress denominator is the GENERATION QUEUE (the planned
   component bundle, e.g. 26 items), NOT the canvas block count.
   Hierarchy headings (scaffolding) and manually-inserted blocks never
   distort it — manual blocks are tracked as a separate "extra" tally.

   Each queue item maps to a canvas block `block-<index>`; its live
   status (done / generating / error / pending) is read from that block.
   ═══════════════════════════════════════════════════════════════════ */

export type BundleItemStatus = 'done' | 'generating' | 'error' | 'pending';

export interface BundleItem {
  index: number;
  title: string;
  componentType: string;
  topic: string;
  chapter: string;
  section: string;
  sectionPath: string[];
  status: BundleItemStatus;
}

export interface TopicRollup {
  topic: string;
  total: number;
  done: number;
  pending: number;
  failed: number;
  /** Queue indices in this topic (for "generate this topic"). */
  indices: number[];
}

export interface BundleModel {
  items: BundleItem[];
  total: number;        // = queue length (the real plan)
  done: number;
  generating: number;
  pending: number;
  failed: number;
  manual: number;       // officer-inserted blocks (separate tally)
  progressPct: number;  // done / total
  topics: TopicRollup[];
  /** Queue indices that still need generating (pending or failed). */
  remainingIndices: number[];
  failedIndices: number[];
}

/** A block is "manual" when the officer inserted it (not from the queue). */
function isManualBlock(b: PageBlock): boolean {
  return (
    b.index < 0 &&
    b.kind !== 'heading' &&
    !/^section:/i.test((b.content || '').trim()) &&
    (b.id.startsWith('block-manual-') || b.id.startsWith('block-copy-') || b.id.startsWith('block-deepbi-'))
  );
}

export function useBundleModel(queue: QueueItem[], blocks: Map<string, PageBlock>): BundleModel {
  return useMemo(() => {
    const items: BundleItem[] = queue.map((q) => {
      const b = blocks.get(`block-${q.index}`);
      const status: BundleItemStatus = !b
        ? 'pending'
        : b.status === 'done'
        ? 'done'
        : b.status === 'generating'
        ? 'generating'
        : b.status === 'error'
        ? 'error'
        : 'pending';
      const [topic = 'General', chapter = '', section = ''] = q.section_path || [];
      return {
        index: q.index,
        title: q.title,
        componentType: q.component_type,
        topic,
        chapter,
        section,
        sectionPath: q.section_path || [],
        status,
      };
    });

    const done = items.filter((i) => i.status === 'done').length;
    const generating = items.filter((i) => i.status === 'generating').length;
    const failed = items.filter((i) => i.status === 'error').length;
    const pending = items.filter((i) => i.status === 'pending').length;
    const manual = Array.from(blocks.values()).filter(isManualBlock).length;
    const total = items.length;

    // Per-topic rollup (officer thinks in topics, not flat indices).
    const topicMap = new Map<string, TopicRollup>();
    for (const it of items) {
      let r = topicMap.get(it.topic);
      if (!r) {
        r = { topic: it.topic, total: 0, done: 0, pending: 0, failed: 0, indices: [] };
        topicMap.set(it.topic, r);
      }
      r.total += 1;
      r.indices.push(it.index);
      if (it.status === 'done') r.done += 1;
      else if (it.status === 'error') r.failed += 1;
      else r.pending += 1; // pending + generating counted as not-yet-done
    }

    const remainingIndices = items.filter((i) => i.status === 'pending' || i.status === 'error').map((i) => i.index);
    const failedIndices = items.filter((i) => i.status === 'error').map((i) => i.index);

    return {
      items,
      total,
      done,
      generating,
      pending,
      failed,
      manual,
      progressPct: total > 0 ? Math.round((done / total) * 100) : 0,
      topics: Array.from(topicMap.values()),
      remainingIndices,
      failedIndices,
    };
  }, [queue, blocks]);
}
