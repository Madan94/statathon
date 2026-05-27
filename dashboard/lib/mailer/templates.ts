export type OtpPurpose = 'signup_verify' | 'login_verify';

export function buildOtpEmail(otp: string, purpose: OtpPurpose, ttlMinutes: number) {
  const action = purpose === 'signup_verify' ? 'complete your sign up' : 'sign in';
  const subject = 'Your BharatStat verification code';
  const text = [
    'BharatStat — Survey intelligence platform',
    '',
    `Use this code to ${action}:`,
    '',
    otp,
    '',
    `This code expires in ${ttlMinutes} minutes.`,
    'If you did not request this, you can ignore this email.',
  ].join('\n');

  const html = `<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Segoe UI,Arial,sans-serif;background:#f4f6f9;margin:0;padding:24px">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;margin:0 auto;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0">
    <tr>
      <td style="background:#0f2d52;padding:20px 24px;border-radius:12px 12px 0 0">
        <h1 style="margin:0;color:#ffffff;font-size:20px">BharatStat</h1>
        <p style="margin:6px 0 0;color:#94a3b8;font-size:12px">Survey intelligence platform</p>
      </td>
    </tr>
    <tr>
      <td style="padding:24px">
        <p style="margin:0 0 16px;color:#1e293b;font-size:15px">Use this code to <strong>${action}</strong>:</p>
        <p style="margin:0 0 20px;font-size:32px;font-weight:700;letter-spacing:8px;color:#0f2d52;text-align:center">${otp}</p>
        <p style="margin:0;color:#64748b;font-size:13px">Expires in ${ttlMinutes} minutes. Do not share this code.</p>
      </td>
    </tr>
  </table>
</body>
</html>`;

  return { subject, text, html };
}
