'use client';

import { DataFilterSpec } from '@/lib/api';

export default function FilterConfigForm({
  value,
  onChange,
}: {
  value: DataFilterSpec;
  onChange: (v: DataFilterSpec) => void;
}) {
  return (
    <div className="space-y-4 text-sm">
      <div>
        <label className="text-xs text-text-muted block mb-1">
          Include columns (comma-separated, optional)
        </label>
        <input
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface"
          value={(value.include_columns || []).join(', ')}
          onChange={(e) =>
            onChange({
              ...value,
              include_columns: e.target.value
                ? e.target.value.split(',').map((s) => s.trim()).filter(Boolean)
                : null,
            })
          }
        />
      </div>
      <div>
        <label className="text-xs text-text-muted block mb-1">
          Exclude columns (comma-separated, optional)
        </label>
        <input
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface"
          value={(value.exclude_columns || []).join(', ')}
          onChange={(e) =>
            onChange({
              ...value,
              exclude_columns: e.target.value
                ? e.target.value.split(',').map((s) => s.trim()).filter(Boolean)
                : null,
            })
          }
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-text-muted block mb-1">Max rows</label>
          <input
            type="number"
            min={1}
            className="w-full rounded-lg border border-border px-3 py-2 bg-surface"
            value={value.max_rows ?? ''}
            onChange={(e) =>
              onChange({
                ...value,
                max_rows: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </div>
        <div>
          <label className="text-xs text-text-muted block mb-1">
            Min complete row %
          </label>
          <input
            type="number"
            min={0}
            max={100}
            className="w-full rounded-lg border border-border px-3 py-2 bg-surface"
            value={value.min_complete_row_pct ?? ''}
            onChange={(e) =>
              onChange({
                ...value,
                min_complete_row_pct: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </div>
      </div>
    </div>
  );
}
