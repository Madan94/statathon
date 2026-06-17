import type { PageBlock } from '../../engine/useCanvasState';
import type { NumberedHeading, TableSplitPart } from '../../engine/paginationEngine';

/* Common props every per-kind content component receives. */
export interface KindProps {
  block: PageBlock;
  isSelected: boolean;
  numerals: 'intl' | 'devanagari';
  numbering?: NumberedHeading;
  tableCaption?: string;
  splitPart?: TableSplitPart;
}
