'use client';

import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { authApi, storeAuthToken } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import { SkeletonCard } from '@/components/ui/Skeleton';

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [oauthLoading, setOauthLoading] = useState(false);

  useEffect(() => {
    const token = searchParams.get('token');
    if (token) {
      setOauthLoading(true);
      storeAuthToken(token);
      router.replace('/upload');
    }
  }, [searchParams, router]);

  const handleGoogle = async () => {
    setError(null);
    try {
      const { url } = await authApi.googleAuthUrl();
      window.location.href = url;
    } catch {
      setError('Google sign-in is not configured on the API (set GOOGLE_OAUTH_* in .env)');
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setInfo(null);
    try {
      if (mode === 'register') {
        await authApi.register(email, password);
        setMode('login');
        setInfo('Account created. Please sign in.');
      } else {
        const data = await authApi.login(email, password);
        if (data.error) {
          setError(data.error);
          return;
        }
        router.push('/upload');
      }
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string } }; message?: string };
      setError(ax.response?.data?.detail || ax.message || 'Request failed');
    } finally {
      setLoading(false);
    }
  };

  if (oauthLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface p-4">
        <SkeletonCard />
        <p className="sr-only">Completing sign-in…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface p-4">
      <div className="w-full max-w-md rounded-xl border border-border bg-surface-card shadow-sm overflow-hidden">
        <div className="bg-primary px-6 py-8 text-center">
          <Link href="/" className="text-2xl font-bold text-white tracking-tight">
            BharatStat
          </Link>
          <p className="text-primary-foreground/80 text-sm mt-1 text-white/80">
            Survey intelligence platform
          </p>
        </div>
        <div className="p-8">
          <h1 className="text-xl font-semibold text-text mb-6">
            {mode === 'login' ? 'Sign in to your account' : 'Create an account'}
          </h1>
          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
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
                className="w-full px-3 py-2 border border-border rounded-lg bg-surface text-text focus:ring-2 focus:ring-accent/40"
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
                minLength={6}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3 py-2 border border-border rounded-lg bg-surface text-text focus:ring-2 focus:ring-accent/40"
              />
            </div>
            {error && <Alert variant="error">{error}</Alert>}
            {info && <Alert variant="info">{info}</Alert>}
            <Button type="submit" disabled={loading} className="w-full">
              {loading ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Register'}
            </Button>
            <Button type="button" variant="outline" className="w-full" onClick={handleGoogle}>
              Sign in with Google
            </Button>
          </form>
          <button
            type="button"
            className="mt-6 text-sm text-primary hover:underline focus-visible:ring-2 focus-visible:ring-accent/40 rounded"
            onClick={() => {
              setMode(mode === 'login' ? 'register' : 'login');
              setError(null);
              setInfo(null);
            }}
          >
            {mode === 'login' ? 'Need an account? Register' : 'Already have an account? Sign in'}
          </button>
          <p className="mt-6 text-center">
            <Link href="/" className="text-sm text-text-muted hover:text-text">
              ← Back to home
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-surface">
          <SkeletonCard />
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
