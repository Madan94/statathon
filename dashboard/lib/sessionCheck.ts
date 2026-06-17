import { ACCESS_COOKIE } from './authConfig';

function accessTokenFromCookie(cookieHeader: string): string | null {
  const match = cookieHeader
    .split(';')
    .map((c) => c.trim())
    .find((c) => c.startsWith(`${ACCESS_COOKIE}=`));
  if (!match) return null;
  return decodeURIComponent(match.slice(ACCESS_COOKIE.length + 1));
}

/** Fast local JWT exp check — avoids /auth/me round-trip on every navigation. */
function isAccessTokenLikelyValid(token: string): boolean {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return false;
    const payload = JSON.parse(
      Buffer.from(parts[1].replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8'),
    ) as { exp?: number };
    if (payload.exp && payload.exp * 1000 <= Date.now()) return false;
    return true;
  } catch {
    return false;
  }
}

/** Server/middleware: validate session via cookie JWT exp or BFF fallback. */
export async function validateSession(requestUrl: string, cookieHeader: string): Promise<boolean> {
  const token = accessTokenFromCookie(cookieHeader);
  if (token && isAccessTokenLikelyValid(token)) {
    return true;
  }
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
