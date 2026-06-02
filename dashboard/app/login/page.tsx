'use client';

import { useState } from 'react';
import Link from 'next/link';
import { authApi, formatApiError } from '@/lib/api';
import { completeAuthAndRedirect } from '@/lib/authSession';
import { toast } from '@/lib/toast';
import AuthWizardLayout from '@/components/auth/AuthWizardLayout';
import OtpInput from '@/components/auth/OtpInput';
import ResendOtpButton from '@/components/auth/ResendOtpButton';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import PasswordInput from '@/components/ui/PasswordInput';

const IS_DEV = process.env.NODE_ENV === 'development';
const DEV_EMAIL = 'officer@example.com';
const DEV_PASSWORD = 'TestOfficer123!';
const DEV_OTP = '123456';

export default function LoginPage() {
  const [step, setStep] = useState<1 | 2>(1);
  const [email, setEmail] = useState(IS_DEV ? DEV_EMAIL : '');
  const [password, setPassword] = useState(IS_DEV ? DEV_PASSWORD : '');
  const [challengeId, setChallengeId] = useState('');
  const [otp, setOtp] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleDevQuickLogin = async () => {
    setLoading(true);
    setError(null);
    try {
      await authApi.devQuickLogin(DEV_EMAIL, DEV_PASSWORD);
      toast.success('Signed in as dev test officer (OTP skipped)');
      await completeAuthAndRedirect();
    } catch (err: unknown) {
      setError(formatApiError(err, 'Dev quick login failed'));
    } finally {
      setLoading(false);
    }
  };

  const handleContinue = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await authApi.loginStart(email, password);
      setChallengeId(res.challenge_id);
      if (res.dev_otp) {
        setOtp(res.dev_otp);
        toast.info(`Dev OTP: ${res.dev_otp} (also printed in API terminal)`);
      } else if (res.dev_otp_logged) {
        toast.info('Check the API terminal (start-api.ps1) for your 6-digit code.');
      } else {
        toast.success('Verification code sent to your email');
      }
      setStep(2);
    } catch (err: unknown) {
      setError(formatApiError(err, 'Invalid email or password'));
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (otp.length < 6) {
      setError('Enter the 6-digit code from your email');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await authApi.loginVerifyOtp(challengeId, otp);
      toast.success('Signed in');
      await completeAuthAndRedirect();
    } catch (err: unknown) {
      setError(formatApiError(err, 'Verification failed'));
    } finally {
      setLoading(false);
    }
  };

  if (step === 1) {
    return (
      <AuthWizardLayout
        variant="login"
        title="Sign in"
        subtitle="Enter your email and password to continue."
        step={1}
      >
        {IS_DEV && (
          <div className="mb-4 rounded-lg border border-dashed border-primary/40 bg-primary/5 p-3 text-xs text-text-muted space-y-2">
            <p className="font-semibold text-primary">Dev test officer</p>
            <p>
              Email: <code className="text-text">{DEV_EMAIL}</code>
            </p>
            <p>
              Password: <code className="text-text">{DEV_PASSWORD}</code>
            </p>
            <p>
              OTP (if prompted): <code className="text-text">{DEV_OTP}</code>
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="w-full"
              disabled={loading}
              onClick={handleDevQuickLogin}
            >
              Dev quick login (skip OTP)
            </Button>
          </div>
        )}
        <form onSubmit={handleContinue} className="space-y-3">
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-text mb-1">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 border border-border rounded-lg bg-white focus:ring-2 focus:ring-accent/40"
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-text mb-1">
              Password
            </label>
            <PasswordInput
              id="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && <Alert variant="error">{error}</Alert>}
          <Button type="submit" disabled={loading} className="w-full">
            {loading ? 'Please wait…' : 'Continue'}
          </Button>
        </form>
        <p className="mt-4 text-center text-xs text-text-muted">
          New officer?{' '}
          <Link href="/signup" className="text-[#0a1f44] font-medium hover:underline">
            Create an account
          </Link>
        </p>
      </AuthWizardLayout>
    );
  }

  return (
    <AuthWizardLayout
      variant="login"
      title="Verify sign-in"
      subtitle={`Enter the code sent to ${email}`}
      step={2}
    >
      <form onSubmit={handleVerify} className="space-y-6">
        <OtpInput value={otp} onChange={setOtp} disabled={loading} />
        {IS_DEV && email === DEV_EMAIL && (
          <p className="text-xs text-text-muted text-center">
            Dev test OTP is always <code>{DEV_OTP}</code>
          </p>
        )}
        {error && <Alert variant="error">{error}</Alert>}
        <Button type="submit" disabled={loading} className="w-full">
          {loading ? 'Verifying…' : 'Continue to platform'}
        </Button>
        <ResendOtpButton
          onResend={async () => {
            const notifySent = (devLogged?: boolean | null, devOtp?: string | null) => {
              if (devOtp) {
                setOtp(devOtp);
                toast.info(`Dev OTP: ${devOtp}`);
              } else if (devLogged) {
                toast.info('Check the API terminal for your 6-digit code.');
              } else {
                toast.success('Verification code sent');
              }
            };
            try {
              const res = await authApi.loginResendOtp(challengeId);
              notifySent(res.dev_otp_logged, res.dev_otp);
            } catch (err: unknown) {
              const detail = formatApiError(err, '');
              const restart =
                detail.toLowerCase().includes('already used') ||
                detail.toLowerCase().includes('invalid or expired');
              if (restart && email && password) {
                const fresh = await authApi.loginStart(email, password);
                setChallengeId(fresh.challenge_id);
                setOtp(fresh.dev_otp || '');
                setError(null);
                notifySent(fresh.dev_otp_logged, fresh.dev_otp);
                return;
              }
              setError(detail || 'Could not resend code. Go back and try again.');
              throw err;
            }
          }}
        />
        <button
          type="button"
          className="w-full text-sm text-text-muted hover:text-text"
          onClick={() => setStep(1)}
        >
          ← Back
        </button>
      </form>
    </AuthWizardLayout>
  );
}
