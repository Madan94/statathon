import { NextRequest, NextResponse } from 'next/server';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function middleware(request: NextRequest) {
  const cookie = request.headers.get('cookie') || '';
  try {
    const res = await fetch(`${API_BASE}/auth/me`, {
      headers: { cookie },
      cache: 'no-store',
    });
    if (!res.ok) {
      const login = new URL('/login', request.url);
      login.searchParams.set('from', request.nextUrl.pathname);
      return NextResponse.redirect(login);
    }
  } catch {
    return NextResponse.next();
  }
  return NextResponse.next();
}

export const config = {
  matcher: ['/upload/:path*', '/datasets/:path*', '/analysis/:path*', '/reports/:path*'],
};
