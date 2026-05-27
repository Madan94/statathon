export type SmtpConfig = {
  host: string;
  port: number;
  secure: boolean;
  user: string;
  pass: string;
  from: string;
};

export type MailerConfigResult =
  | { ok: true; config: SmtpConfig }
  | { ok: false; error: string };

function cleanPass(raw: string): string {
  return raw.replace(/\s+/g, '');
}

export function getSmtpConfig(): MailerConfigResult {
  const host = process.env.SMTP_HOST?.trim();
  const user = process.env.SMTP_USER?.trim();
  const pass = process.env.SMTP_PASS?.trim();
  const from = process.env.SMTP_FROM?.trim() || 'BharatStat <noreply@localhost>';
  const port = Number(process.env.SMTP_PORT || '587');

  if (!host) {
    return { ok: false, error: 'SMTP_HOST is not set in dashboard/.env.local' };
  }
  if (!user) {
    return { ok: false, error: 'SMTP_USER is not set in dashboard/.env.local' };
  }
  if (!pass) {
    return { ok: false, error: 'SMTP_PASS is not set in dashboard/.env.local' };
  }

  return {
    ok: true,
    config: {
      host,
      port,
      secure: port === 465,
      user,
      pass: cleanPass(pass),
      from,
    },
  };
}

export function isDevLogOtpEnabled(): boolean {
  return process.env.SMTP_DEV_LOG_OTP === 'true';
}
