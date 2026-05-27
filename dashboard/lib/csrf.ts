/** Read CSRF cookie for double-submit header on mutating API calls. */

export function getCsrfToken(): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(/(?:^|;\s*)bharatstat_csrf=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}
