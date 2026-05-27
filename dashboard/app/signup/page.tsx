'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { authApi } from '@/lib/api';
import { toast } from '@/lib/toast';
import AuthWizardLayout from '@/components/auth/AuthWizardLayout';
import OtpInput from '@/components/auth/OtpInput';
import ResendOtpButton from '@/components/auth/ResendOtpButton';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';

export default function SignupPage() {
  const router = useRouter();
  const [step, setStep] = useState<1 | 2>(1);
  const [fullName, setFullName] = useState('');
  const [officerRole, setOfficerRole] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [challengeId, setChallengeId] = useState('');
  const [otp, setOtp] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleContinue = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await authApi.signupStart({
        full_name: fullName,
        officer_role: officerRole,
        email,
        password,
      });
      setChallengeId(res.challenge_id);
      setStep(2);
      if (res.dev_otp_logged) {
        toast.info(
          'SMTP not configured — open the npm run dev terminal; the 6-digit code is printed there.'
        );
      } else {
        toast.success('Verification code sent to your email');
      }
    } catch (err: unknown) {
      const ax = err as {
        response?: { data?: { detail?: string } };
        message?: string;
        code?: string;
      };
      const detail = ax.response?.data?.detail;
      if (detail) {
        setError(typeof detail === 'string' ? detail : JSON.stringify(detail));
      } else if (ax.code === 'ERR_NETWORK' || ax.message?.includes('Network')) {
        setError('Cannot reach the API. Start the server on http://127.0.0.1:8000 and check NEXT_PUBLIC_API_URL.');
      } else {
        setError(ax.message || 'Signup failed');
      }
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
      await authApi.signupVerifyOtp(challengeId, otp);
      toast.success('Account verified');
      router.push('/upload');
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string } } };
      setError(ax.response?.data?.detail || 'Verification failed');
    } finally {
      setLoading(false);
    }
  };

  if (step === 1) {
    return (
      <AuthWizardLayout
        title="Create your officer account"
        subtitle="Enter your details to register with BharatStat."
        step={1}
      >
        <form onSubmit={handleContinue} className="space-y-4">
          <div>
            <label htmlFor="fullName" className="block text-sm font-medium text-text mb-1">
              Name
            </label>
            <input
              id="fullName"
              required
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="w-full px-3 py-2 border border-border rounded-lg bg-white focus:ring-2 focus:ring-accent/40"
            />
          </div>
          <div>
            <label htmlFor="officerRole" className="block text-sm font-medium text-text mb-1">
              Role of the Officer
            </label>
            <input
              id="officerRole"
              required
              value={officerRole}
              onChange={(e) => setOfficerRole(e.target.value)}
              placeholder="e.g. Statistical Officer, Director"
              className="w-full px-3 py-2 border border-border rounded-lg bg-white focus:ring-2 focus:ring-accent/40"
            />
          </div>
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
            <input
              id="password"
              type="password"
              required
              minLength={12}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 border border-border rounded-lg bg-white focus:ring-2 focus:ring-accent/40"
            />
            <p className="text-xs text-text-muted mt-1">At least 12 characters with letters and numbers</p>
          </div>
          {error && <Alert variant="error">{error}</Alert>}
          <Button type="submit" disabled={loading} className="w-full">
            {loading ? 'Please wait…' : 'Continue'}
          </Button>
        </form>
        <p className="mt-6 text-center text-sm text-text-muted">
          Already have an account?{' '}
          <Link href="/login" className="text-primary hover:underline">
            Sign in
          </Link>
        </p>
      </AuthWizardLayout>
    );
  }

  return (
    <AuthWizardLayout
      title="Verify your email"
      subtitle={`We sent a 6-digit code to ${email}`}
      step={2}
    >
      <form onSubmit={handleVerify} className="space-y-6">
        <OtpInput value={otp} onChange={setOtp} disabled={loading} />
        {error && <Alert variant="error">{error}</Alert>}
        <Button type="submit" disabled={loading} className="w-full">
          {loading ? 'Verifying…' : 'Continue'}
        </Button>
        <ResendOtpButton
          onResend={async () => {
            const res = await authApi.signupResendOtp(challengeId);
            if (res.dev_otp_logged) {
              toast.info('Check API logs for OTP (dev mode)');
            } else {
              toast.success('Code resent');
            }
          }}
        />
        <button
          type="button"
          className="w-full text-sm text-text-muted hover:text-text"
          onClick={() => setStep(1)}
        >
          ← Back to details
        </button>
      </form>
    </AuthWizardLayout>
  );
}
