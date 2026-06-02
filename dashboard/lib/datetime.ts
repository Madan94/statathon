/**
 * API timestamps from Python use datetime.utcnow() and isoformat() without "Z".
 * Treat naive strings as UTC before formatting to India time.
 */
export function parseApiUtcTimestamp(iso: string): Date {
  const trimmed = iso.trim();
  if (!trimmed) return new Date(NaN);
  if (/[zZ]$/.test(trimmed) || /[+-]\d{2}:\d{2}$/.test(trimmed)) {
    return new Date(trimmed);
  }
  return new Date(`${trimmed}Z`);
}

export function formatIndiaTime(iso?: string | null): string {
  if (!iso) return '—';
  const date = parseApiUtcTimestamp(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  }).format(date);
}
