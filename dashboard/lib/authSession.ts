import type { AppRouterInstance } from 'next/dist/shared/lib/app-router-context.shared-runtime';
import { authApi } from './api';
import { isSafeInternalPath, PLATFORM_HOME, resolvePostLoginPath } from './authConfig';

/** Clear httpOnly session cookies via API + client-visible CSRF cookie. */
export async function clearStaleSession(): Promise<void> {
  try {
    await fetch('/api/backend/auth/logout', { method: 'POST', credentials: 'include' });
  } catch {
    // Ignore network errors; still clear client-readable cookies below.
  }
  if (typeof document !== 'undefined') {
    document.cookie = 'bharatstat_csrf=; Max-Age=0; path=/; samesite=strict';
  }
}

/** Confirm session, then hard-navigate so login/signup are not in browser history. */
export async function completeAuthAndRedirect(
  _router?: AppRouterInstance,
  destination: string = PLATFORM_HOME
): Promise<void> {
  await authApi.me();
  const target = destination;
  if (typeof window !== 'undefined') {
    window.location.replace(target);
    return;
  }
}

/** Send user to login; optional return path after successful auth. */
export function redirectToLogin(fromPath?: string): void {
  if (typeof window === 'undefined') return;
  const from =
    fromPath && isSafeInternalPath(fromPath) ? `?from=${encodeURIComponent(fromPath)}` : '';
  window.location.replace(`/login${from}`);
}

export { resolvePostLoginPath };
