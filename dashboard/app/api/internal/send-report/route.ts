import { NextRequest, NextResponse } from 'next/server';

function checkSecret(request: NextRequest): NextResponse | null {
  const secret = process.env.MAIL_INTERNAL_SECRET?.trim();
  if (!secret) {
    return NextResponse.json({ detail: 'MAIL_INTERNAL_SECRET not configured' }, { status: 503 });
  }
  const header = request.headers.get('X-Mail-Internal-Secret');
  if (header !== secret) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }
  return null;
}

export async function POST(request: NextRequest) {
  const denied = checkSecret(request);
  if (denied) return denied;

  let body: {
    to?: string;
    job_id?: number;
    content_hash?: string | null;
    filename?: string;
    pdf_base64?: string;
  };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: 'Invalid JSON' }, { status: 400 });
  }

  const to = body.to?.trim();
  const pdfB64 = body.pdf_base64;
  if (!to || !pdfB64) {
    return NextResponse.json({ detail: 'to and pdf_base64 required' }, { status: 400 });
  }

  const filename = body.filename || `statathon-report-${body.job_id ?? 'export'}.pdf`;
  const hashLine = body.content_hash ? `\nContent hash: ${body.content_hash}` : '';

  const { getTransport } = await import('@/lib/mailer/transport');
  const tr = getTransport();
  if ('error' in tr) {
    return NextResponse.json({ detail: tr.error, sent: false }, { status: 503 });
  }

  try {
    const info = await tr.transport.sendMail({
      from: tr.config.from,
      to,
      subject: `BharatStat report${body.job_id ? ` #${body.job_id}` : ''}`,
      text: `Your BharatStat report is attached.${hashLine}`,
      attachments: [
        {
          filename,
          content: Buffer.from(pdfB64, 'base64'),
          contentType: 'application/pdf',
        },
      ],
    });
    return NextResponse.json({ ok: true, sent: true, messageId: info.messageId });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ detail: msg, sent: false }, { status: 503 });
  }
}
