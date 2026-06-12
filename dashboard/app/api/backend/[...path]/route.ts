import { NextRequest, NextResponse } from 'next/server';

const BACKEND =
  process.env.API_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  'http://127.0.0.1:8000';

// 1 hour — covers the longest extraction jobs without timing out
const PROXY_TIMEOUT_MS = 60 * 60 * 1000;

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
  // Forward Accept header so SSE clients get text/event-stream
  const accept = req.headers.get('accept');
  if (accept) headers.set('accept', accept);

  const init: RequestInit = {
    method: req.method,
    headers,
    redirect: 'manual',
    // AbortSignal.timeout available in Node 18+; prevents OS-level socket kills on long jobs
    signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
  };
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    init.body = await req.arrayBuffer();
  }

  const upstream = await fetch(target, init);
  const resHeaders = new Headers();

  const upstreamContentType = upstream.headers.get('content-type') || '';
  const isSSE = upstreamContentType.includes('text/event-stream');

  // Always forward these headers
  for (const name of ['content-type', 'content-disposition', 'cache-control', 'transfer-encoding']) {
    const value = upstream.headers.get(name);
    if (value) resHeaders.set(name, value);
  }

  // SSE-specific: disable buffering at every proxy layer so events reach the browser instantly
  if (isSSE) {
    resHeaders.set('cache-control', 'no-cache, no-store');
    resHeaders.set('connection', 'keep-alive');
    resHeaders.set('x-accel-buffering', 'no');   // nginx upstream buffering off
    resHeaders.set('x-content-type-options', 'nosniff');
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
