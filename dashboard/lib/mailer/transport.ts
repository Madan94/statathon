import nodemailer from 'nodemailer';
import type Transporter from 'nodemailer/lib/mailer';
import { getSmtpConfig, type SmtpConfig } from './config';

let cached: Transporter | null = null;
let cachedKey: string | null = null;

function cacheKey(c: SmtpConfig): string {
  return `${c.host}:${c.port}:${c.user}`;
}

export function createSmtpTransport(config: SmtpConfig): Transporter {
  return nodemailer.createTransport({
    host: config.host,
    port: config.port,
    secure: config.secure,
    auth: {
      user: config.user,
      pass: config.pass,
    },
    tls: {
      minVersion: 'TLSv1.2',
    },
  });
}

export function getTransport(): { transport: Transporter; config: SmtpConfig } | { error: string } {
  const loaded = getSmtpConfig();
  if (!loaded.ok) {
    return { error: loaded.error };
  }

  const key = cacheKey(loaded.config);
  if (!cached || cachedKey !== key) {
    cached = createSmtpTransport(loaded.config);
    cachedKey = key;
  }

  return { transport: cached, config: loaded.config };
}

export async function verifySmtpConnection(): Promise<{ ok: true } | { ok: false; error: string }> {
  const result = getTransport();
  if ('error' in result) {
    return { ok: false, error: result.error };
  }
  try {
    await result.transport.verify();
    return { ok: true };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, error: msg };
  }
}
