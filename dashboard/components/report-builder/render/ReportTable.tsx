'use client';

/**
 * R3 — MoSPI table for the preview. Mirrors `render/tables.py`: multi-row
 * column-group header, right-aligned Indian/percent measure cells, bold
 * subtotal/total rows, em-dash blanks, sticky + repeating header, and footnote
 * Source/Note markers. Clicking a measure cell surfaces its provenance.
 */
import type {
  Column,
  EditInput,
  Locale,
  NumberSystem,
  Table,
  TableRow,
} from '@/lib/report/types';
import { formatValue, loc } from '@/lib/report/format';
import type { ProvenanceTarget } from './ProvenanceDrawer';
import { EditableField } from './EditableField';

const TOTAL_LABELS = new Set([
  'all-india', 'all india', 'total', 'grand total', 'overall', 'india',
]);

const EM_DASH = '\u2014';

function isMeasure(c: Column): boolean {
  return c.role === 'measure';
}

function alignClass(c: Column): string {
  if (c.align === 'right' || isMeasure(c)) return 'text-right tabular-nums';
  if (c.align === 'center') return 'text-center';
  return 'text-left';
}

function rowIsTotal(row: TableRow, columns: Column[]): boolean {
  if (row.isTotal || row.isSubtotal) return true;
  const firstDim = columns.find((c) => !isMeasure(c));
  if (firstDim) {
    const v = row[firstDim.columnId];
    if (typeof v === 'string' && TOTAL_LABELS.has(v.trim().toLowerCase())) return true;
  }
  return false;
}

function GroupHeader({
  columns,
  groups,
  locale,
}: {
  columns: Column[];
  groups: NonNullable<Table['columnGroups']>;
  locale: Locale;
}) {
  const groupOf = new Map<string, NonNullable<Table['columnGroups']>[number]>();
  for (const g of groups) for (const ref of g.spanRefs ?? []) groupOf.set(ref, g);

  const cells: React.ReactNode[] = [];
  let i = 0;
  while (i < columns.length) {
    const col = columns[i];
    const g = groupOf.get(col.columnId);
    if (g) {
      const span = (g.spanRefs?.length ?? 1) || 1;
      cells.push(
        <th key={`g-${g.groupId}`} colSpan={span} className="border border-border bg-border/30 px-3 py-1.5 text-center font-semibold">
          {loc(g.label, locale)}
        </th>,
      );
      i += span;
    } else {
      cells.push(<th key={`g-empty-${i}`} className="border border-border" />);
      i += 1;
    }
  }
  return <tr>{cells}</tr>;
}

interface Props {
  table: Table;
  locale?: Locale;
  numberSystem?: NumberSystem;
  onValueClick?: (t: ProvenanceTarget) => void;
  editable?: boolean;
  onEdit?: (edit: EditInput) => Promise<void>;
}

export function ReportTable({
  table,
  locale = 'en-IN',
  numberSystem = 'indian',
  onValueClick,
  editable,
  onEdit,
}: Props) {
  const columns = table.columns ?? [];
  const groups = table.columnGroups ?? [];
  const rows = table.rows ?? [];
  if (!columns.length) {
    return <div className="text-sm italic text-red-600">[table has no columns]</div>;
  }

  return (
    <figure className="my-4">
      {table.title && (
        <figcaption className="mb-1.5 text-sm font-semibold text-text">
          {loc(table.title, locale)}
        </figcaption>
      )}
      <div className="max-h-[70vh] overflow-auto rounded-lg border border-border">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-surface">
            {groups.length > 0 && (
              <GroupHeader columns={columns} groups={groups} locale={locale} />
            )}
            <tr>
              {columns.map((c) => (
                <th
                  key={c.columnId}
                  scope="col"
                  className={`border border-border bg-border/20 px-3 py-1.5 ${alignClass(c)}`}
                >
                  {loc(c.header, locale)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => {
              const total = rowIsTotal(row, columns);
              return (
                <tr key={ri} className={total ? 'font-bold' : ri % 2 ? 'bg-border/10' : ''}>
                  {columns.map((c) => {
                    const raw = row[c.columnId];
                    if (isMeasure(c)) {
                      const display = formatValue(raw, {
                        unit: c.unit,
                        fmt: c.format,
                        system: numberSystem,
                        empty: EM_DASH,
                      });
                      if (editable && onEdit) {
                        const ov = row.overridden;
                        const isOv = Array.isArray(ov) && ov.includes(c.columnId);
                        return (
                          <td
                            key={c.columnId}
                            className={`border border-border px-3 py-1.5 ${alignClass(c)}`}
                          >
                            <EditableField
                              kind="number"
                              value={typeof raw === 'number' ? raw : Number(raw) || 0}
                              display={display}
                              overridden={isOv}
                              onCommit={(val, reason) =>
                                onEdit({
                                  target: {
                                    kind: 'table_cell',
                                    id: table.tableId,
                                    col: c.columnId,
                                    rowIds: row.rowIds,
                                  },
                                  value: val,
                                  reason,
                                })
                              }
                            />
                          </td>
                        );
                      }
                      const clickable = Boolean(onValueClick) && raw != null;
                      return (
                        <td
                          key={c.columnId}
                          className={`border border-border px-3 py-1.5 ${alignClass(c)} ${
                            clickable ? 'cursor-pointer hover:bg-accent/10' : ''
                          }`}
                          onClick={
                            clickable
                              ? () =>
                                  onValueClick?.({
                                    label: loc(c.header, locale),
                                    value: display,
                                    rowIds: row.rowIds,
                                    provenance: table.provenance,
                                  })
                              : undefined
                          }
                        >
                          {display}
                        </td>
                      );
                    }
                    return (
                      <td key={c.columnId} className={`border border-border px-3 py-1.5 ${alignClass(c)}`}>
                        {raw == null ? EM_DASH : loc(raw as string, locale)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {table.footnotes && table.footnotes.length > 0 && (
        <ul className="mt-1.5 list-disc pl-5 text-xs text-text-muted">
          {table.footnotes
            .filter((fn) => fn.text)
            .map((fn, i) => {
              const text = loc(fn.text, locale);
              const nid = (fn.noteId ?? '').toLowerCase();
              const low = text.trim().toLowerCase();
              let marker = '';
              if (nid.includes('source') && !low.startsWith('source:')) marker = 'Source: ';
              else if (nid.includes('note') && !low.startsWith('note:')) marker = 'Note: ';
              return (
                <li key={i}>
                  {marker && <span className="font-semibold text-text">{marker}</span>}
                  {text}
                </li>
              );
            })}
        </ul>
      )}
    </figure>
  );
}
