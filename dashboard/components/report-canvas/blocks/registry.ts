import type { PageBlock } from '../engine/useCanvasState';
import type { KindProps } from './kinds/types';
import { HeadingBlock } from './kinds/HeadingBlock';
import { NarrativeBlock } from './kinds/NarrativeBlock';
import { KeyFindingBlock } from './kinds/KeyFindingBlock';
import { TableBlock } from './kinds/TableBlock';
import { MetricBlock } from './kinds/MetricBlock';
import { ChartBlock } from './kinds/ChartBlock';
import { SourceNoteBlock } from './kinds/SourceNoteBlock';
import { DividerBlock } from './kinds/DividerBlock';

/* ═══════════════════════════════════════════════════════════════════
   Block registry — maps a block kind to the component that renders its
   "done" content. Adding a new block type is now a one-line entry here
   plus a component under kinds/, instead of another branch in a monolith.
   ═══════════════════════════════════════════════════════════════════ */

export const BLOCK_REGISTRY: Record<PageBlock['kind'], React.ComponentType<KindProps>> = {
  heading: HeadingBlock,
  narrative: NarrativeBlock,
  key_finding: KeyFindingBlock,
  table: TableBlock,
  metric: MetricBlock,
  chart: ChartBlock,
  source_note: SourceNoteBlock,
  divider: DividerBlock,
};
