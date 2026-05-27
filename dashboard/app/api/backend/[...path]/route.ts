import { NextRequest, NextResponse } from 'next/server';

const BACKEND =
  process.env.API_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  'http://127.0.0.1:8000';

async function proxy(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const pathname = path.join('/');
  const target = `${BACKEND.replace(/\/$/, '')}/${pathname}${req.nextUrl.search}`;

  const headers = new Headers();
  const contentType = req.headers.get('content-type');
  if (contentType) headers.set('content-type', contentType);
  const cookie = req.headers.get('cookie');
  if (cookie) headers.set('cookie', cookie);
  const csrf = req.headers.get('x-csrf-token');
  if (csrf) headers.set('x-csrf-token', csrf);
  const authorization = req.headers.get('authorization');
  if (authorization) headers.set('authorization', authorization);

  const init: RequestInit = {
    method: req.method,
    headers,
    redirect: 'manual',
  };
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    init.body = await req.arrayBuffer();
  }

  const upstream = await fetch(target, init);
  const resHeaders = new Headers();

  for (const name of ['content-type', 'content-disposition', 'cache-control']) {
    const value = upstream.headers.get(name);
    if (value) resHeaders.set(name, value);
  }

  if (typeof upstream.headers.getSetCookie === 'function') {
    for (const c of upstream.headers.getSetCookie()) {
      resHeaders.append('set-cookie', c);
    }
  } else {
    const raw = upstream.headers.get('set-cookie');
    if (raw) resHeaders.set('set-cookie', raw);
  }

  return new NextResponse(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: resHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
