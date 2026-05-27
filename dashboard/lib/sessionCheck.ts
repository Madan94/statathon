import { ACCESS_COOKIE } from './authConfig';

/** Server/middleware: validate session via same-origin BFF. */
export async function validateSession(requestUrl: string, cookieHeader: string): Promise<boolean> {
  try {
    const meUrl = new URL('/api/backend/auth/me', requestUrl);
    const res = await fetch(meUrl, {
      headers: { cookie: cookieHeader },
      cache: 'no-store',
    });
    return res.ok;
  } catch {
    return false;
  }
}

export function hasAccessCookie(cookieHeader: string | null): boolean {
  if (!cookieHeader) return false;
  return cookieHeader.split(';').some((c) => c.trim().startsWith(`${ACCESS_COOKIE}=`));
}
