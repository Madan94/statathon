// ─────────────────────────────────────────────────────────────────────────────
// Lightweight client-side CSV parsing helpers for the binding workbench.
// Shared by DatasetWeightTabs (weighting) and QueryIndicatorFilters (filtering)
// so the in-browser uploaded file is parsed the same way in both places.
// ─────────────────────────────────────────────────────────────────────────────

export interface ParsedCsv {
  headers: string[];
  rows: string[][];
  totalDataRows: number;
  truncated: boolean;
}

/** Minimal RFC-4180-ish CSV parser: handles quoted fields, escaped quotes, CRLF. */
export function parseCsv(text: string, maxRows: number): ParsedCsv {
  const records: string[][] = [];
  let field = '';
  let row: string[] = [];
  let inQuotes = false;
  let i = 0;
  const n = text.length;
  if (n > 0 && text.charCodeAt(0) === 0xfeff) i = 1; // strip BOM

  const pushField = () => {
    row.push(field);
    field = '';
  };
  const pushRow = () => {
    pushField();
    records.push(row);
    row = [];
  };

  while (i < n) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i += 1;
        continue;
      }
      field += ch;
      i += 1;
      continue;
    }
    if (ch === '"') {
      inQuotes = true;
      i += 1;
      continue;
    }
    if (ch === ',') {
      pushField();
      i += 1;
      continue;
    }
    if (ch === '\r') {
      i += 1;
      continue;
    }
    if (ch === '\n') {
      pushRow();
      i += 1;
      if (records.length > maxRows) break;
      continue;
    }
    field += ch;
    i += 1;
  }
  // trailing field / row (no final newline)
  if (field.length > 0 || row.length > 0) pushRow();

  const headers = records.length ? records[0].map((h) => h.trim()) : [];
  const allData = records.slice(1).filter((r) => r.some((c) => c.trim() !== ''));
  const totalDataRows = allData.length;
  const truncated = totalDataRows >= maxRows;
  return { headers, rows: allData, totalDataRows, truncated };
}

/** Parse a CSV cell into a finite number, tolerating thousands separators / spaces. */
export function toNumber(raw: string | undefined): number | null {
  if (raw == null) return null;
  const s = raw.trim().replace(/,/g, '');
  if (s === '') return null;
  const num = Number(s);
  return Number.isFinite(num) ? num : null;
}

/** A column is numeric if ≥80% of its non-empty values parse as finite numbers. */
export function detectNumericColumns(parsed: ParsedCsv): Set<string> {
  const out = new Set<string>();
  parsed.headers.forEach((header, idx) => {
    let nonEmpty = 0;
    let numeric = 0;
    for (const r of parsed.rows) {
      const v = r[idx];
      if (v == null || v.trim() === '') continue;
      nonEmpty += 1;
      if (toNumber(v) !== null) numeric += 1;
    }
    if (nonEmpty > 0 && numeric / nonEmpty >= 0.8) out.add(header);
  });
  return out;
}
