import { NextRequest, NextResponse } from 'next/server';
import { sendOtpEmail, type OtpPurpose } from '@/lib/mailer/index';

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

  let body: { to?: string; otp?: string; purpose?: string; subject?: string; text?: string; html?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: 'Invalid JSON' }, { status: 400 });
  }

  // Preferred contract: API sends otp + purpose; Nodemailer builds the email
  if (body.otp && body.to && body.purpose) {
    const purpose = body.purpose as OtpPurpose;
    if (purpose !== 'signup_verify' && purpose !== 'login_verify') {
      return NextResponse.json({ detail: 'Invalid purpose' }, { status: 400 });
    }
    const result = await sendOtpEmail(body.to, body.otp, purpose);
    if (result.sent) {
      return NextResponse.json({ ok: true, sent: true, messageId: result.messageId });
    }
    if ('dev' in result && result.dev) {
      return NextResponse.json({
        ok: true,
        sent: false,
        dev: true,
        reason: result.reason,
      });
    }
    const errMsg = 'error' in result ? result.error : 'Failed to send email';
    return NextResponse.json({ detail: errMsg, sent: false }, { status: 503 });
  }

  // Legacy: pre-built subject/text/html (still via Nodemailer transport only)
  const { to, subject, text, html } = body;
  if (!to || !subject || !text) {
    return NextResponse.json(
      { detail: 'Provide { to, otp, purpose } or { to, subject, text, html? }' },
      { status: 400 }
    );
  }

  const { getTransport } = await import('@/lib/mailer/transport');
  const tr = getTransport();
  if ('error' in tr) {
    return NextResponse.json({ detail: tr.error, sent: false }, { status: 503 });
  }
  try {
    const info = await tr.transport.sendMail({
      from: tr.config.from,
      to,
      subject,
      text,
      html: html || text,
    });
    return NextResponse.json({ ok: true, sent: true, messageId: info.messageId });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ detail: msg, sent: false }, { status: 503 });
  }
}
