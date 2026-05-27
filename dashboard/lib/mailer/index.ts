import { getSmtpConfig, isDevLogOtpEnabled } from './config';
import { buildOtpEmail, type OtpPurpose } from './templates';
import { getTransport } from './transport';

export type SendOtpResult =
  | { sent: true; messageId?: string }
  | { sent: false; dev: true; otp?: string; reason: string }
  | { sent: false; error: string };

export async function sendOtpEmail(
  to: string,
  otp: string,
  purpose: OtpPurpose
): Promise<SendOtpResult> {
  const ttl = Number(process.env.OTP_TTL_MINUTES || '10');
  const { subject, text, html } = buildOtpEmail(otp, purpose, ttl);

  const loaded = getSmtpConfig();
  if (!loaded.ok) {
    if (isDevLogOtpEnabled()) {
      console.warn('[nodemailer] Dev log OTP (SMTP incomplete):', { to, otp, reason: loaded.error });
      return { sent: false, dev: true, otp, reason: loaded.error };
    }
    return { sent: false, error: loaded.error };
  }

  const tr = getTransport();
  if ('error' in tr) {
    return { sent: false, error: tr.error };
  }

  try {
    const info = await tr.transport.sendMail({
      from: tr.config.from,
      to,
      subject,
      text,
      html,
    });
    console.info('[nodemailer] OTP sent to', to, 'id:', info.messageId);
    return { sent: true, messageId: info.messageId };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error('[nodemailer] send failed:', msg);
    return { sent: false, error: msg };
  }
}

export { verifySmtpConnection } from './transport';
export { getSmtpConfig } from './config';
export type { OtpPurpose } from './templates';
