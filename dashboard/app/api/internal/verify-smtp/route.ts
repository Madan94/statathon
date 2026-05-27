import { NextRequest, NextResponse } from 'next/server';
import { getSmtpConfig } from '@/lib/mailer/config';
import { verifySmtpConnection } from '@/lib/mailer/transport';

/** Dev/admin: verify Nodemailer can connect to SMTP (same secret as send-otp). */
export async function GET(request: NextRequest) {
  const secret = process.env.MAIL_INTERNAL_SECRET?.trim();
  const header = request.headers.get('X-Mail-Internal-Secret');
  if (!secret || header !== secret) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  const cfg = getSmtpConfig();
  if (!cfg.ok) {
    return NextResponse.json({ ok: false, error: cfg.error }, { status: 503 });
  }

  const verified = await verifySmtpConnection();
  if (!verified.ok) {
    return NextResponse.json(
      { ok: false, host: cfg.config.host, port: cfg.config.port, error: verified.error },
      { status: 503 }
    );
  }

  return NextResponse.json({
    ok: true,
    host: cfg.config.host,
    port: cfg.config.port,
    user: cfg.config.user,
    from: cfg.config.from,
  });
}
