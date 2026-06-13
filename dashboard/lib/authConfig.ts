/** Central auth routing and cookie constants for the dashboard. */

export const ACCESS_COOKIE = 'bharatstat_access';

/** Default landing route after sign-in / sign-up. */
export const PLATFORM_HOME = '/dashboard';

export const AUTH_ROUTES = ['/login', '/signup'] as const;

export const PUBLIC_ROUTES = ['/', '/login', '/signup'] as const;

export const PROTECTED_PREFIXES = [
  '/dashboard',
  '/upload',
  '/datasets',
  '/analysis',
  '/reports',
  '/report-builder',
  '/report',
  '/profile',
  '/activity',
] as const;

export function isAuthRoute(pathname: string): boolean {
  return (AUTH_ROUTES as readonly string[]).includes(pathname);
}

export function isProtectedRoute(pathname: string): boolean {
  return PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
}

/** Only allow same-origin relative paths (no open redirects). */
export function isSafeInternalPath(path: string | null | undefined): path is string {
  if (!path || !path.startsWith('/') || path.startsWith('//')) return false;
  if (isAuthRoute(path)) return false;
  if (path.startsWith('/api')) return false;
  return true;
}

export function resolvePostLoginPath(from: string | null | undefined): string {
  return isSafeInternalPath(from) ? from : PLATFORM_HOME;
}
