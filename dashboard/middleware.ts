import { NextRequest, NextResponse } from 'next/server';
import {
  ACCESS_COOKIE,
  isAuthRoute,
  isProtectedRoute,
  resolvePostLoginPath,
} from './lib/authConfig';
import { hasAccessCookie, validateSession } from './lib/sessionCheck';

export async function middleware(request: NextRequest) {
  const { pathname, searchParams } = request.nextUrl;
  const cookieHeader = request.headers.get('cookie') || '';
  const hasCookie =
    Boolean(request.cookies.get(ACCESS_COOKIE)?.value) || hasAccessCookie(cookieHeader);

  const sessionOk = hasCookie ? await validateSession(request.url, cookieHeader) : false;

  // Already signed in — keep users off login/signup (fixes browser Back to auth pages)
  if (isAuthRoute(pathname)) {
    if (sessionOk) {
      const destination = resolvePostLoginPath(searchParams.get('from'));
      return NextResponse.redirect(new URL(destination, request.url));
    }
    return NextResponse.next();
  }

  // Platform routes require a valid session
  if (isProtectedRoute(pathname)) {
    if (sessionOk) {
      return NextResponse.next();
    }
    const login = new URL('/login', request.url);
    login.searchParams.set('from', pathname);
    return NextResponse.redirect(login);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    '/login',
    '/signup',
    '/dashboard',
    '/dashboard/:path*',
    '/upload',
    '/upload/:path*',
    '/datasets/:path*',
    '/analysis/:path*',
    '/reports/:path*',
    '/report-builder',
    '/report-builder/:path*',
    '/activity',
    '/activity/:path*',
    '/profile',
    '/profile/:path*',
  ],
};
