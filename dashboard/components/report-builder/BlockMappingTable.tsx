'use client';

const KINDS = ['narrative', 'table', 'chart', 'metric', 'heading', 'list'];
const SOURCES = [
  '',
  'semantic_mapping',
  'clusters',
  'health_summary',
  'phase3.anomaly_candidates',
  'phase3.imputation_candidates',
  'missing_per_column',
  'column_types',
  'schema_graph',
];

export type BlockRow = {
  block_id: string;
  kind: string;
  title: string;
  section: string;
  required: boolean;
  hints: { source?: string; engine?: string };
};

export default function BlockMappingTable({
  blocks,
  onChange,
}: {
  blocks: BlockRow[];
  onChange: (blocks: BlockRow[]) => void;
}) {
  const update = (idx: number, patch: Partial<BlockRow>) => {
    const next = blocks.map((b, i) => (i === idx ? { ...b, ...patch } : b));
    onChange(next);
  };

  return (
    <div className="overflow-x-auto border border-border rounded-xl">
      <table className="min-w-full text-sm">
        <thead className="bg-[#f8fafc] text-left text-xs uppercase text-[#64748b]">
          <tr>
            <th className="px-3 py-2">ID</th>
            <th className="px-3 py-2">Kind</th>
            <th className="px-3 py-2">Title</th>
            <th className="px-3 py-2">Section</th>
            <th className="px-3 py-2">Data source</th>
          </tr>
        </thead>
        <tbody>
          {blocks.map((b, i) => (
            <tr key={b.block_id + i} className="border-t border-border">
              <td className="px-3 py-2 font-mono text-xs">{b.block_id}</td>
              <td className="px-3 py-2">
                <select
                  className="rounded border border-border px-2 py-1 bg-surface"
                  value={b.kind}
                  onChange={(e) => update(i, { kind: e.target.value })}
                >
                  {KINDS.map((k) => (
                    <option key={k} value={k}>
                      {k}
                    </option>
                  ))}
                </select>
              </td>
              <td className="px-3 py-2">
                <input
                  className="w-full rounded border border-border px-2 py-1"
                  value={b.title}
                  onChange={(e) => update(i, { title: e.target.value })}
                />
              </td>
              <td className="px-3 py-2">
                <input
                  className="w-full rounded border border-border px-2 py-1"
                  value={b.section}
                  onChange={(e) => update(i, { section: e.target.value })}
                />
              </td>
              <td className="px-3 py-2">
                <select
                  className="rounded border border-border px-2 py-1 bg-surface"
                  value={b.hints?.source || ''}
                  onChange={(e) =>
                    update(i, {
                      hints: { ...b.hints, source: e.target.value || undefined },
                    })
                  }
                >
                  {SOURCES.map((s) => (
                    <option key={s || 'none'} value={s}>
                      {s || '—'}
                    </option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
