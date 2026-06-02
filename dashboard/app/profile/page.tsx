'use client';

import { useEffect, useState } from 'react';
import { Loader2, LogOut, Mail, Shield, User } from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import Card from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import { authApi, type AuthUser } from '@/lib/api';

function ProfileField({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: typeof User;
}) {
  return (
    <div className="flex items-start gap-4 rounded-xl border border-[#e2e8f0] bg-[#f8fafc] p-4">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#fffbeb] text-[#0a1f44]">
        <Icon className="h-5 w-5" aria-hidden />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-[#64748b]">{label}</p>
        <p className="mt-1 text-base font-medium text-[#0a1f44] break-words">{value}</p>
      </div>
    </div>
  );
}

export default function ProfilePage() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await authApi.me();
        if (!cancelled) setUser(me);
      } catch {
        if (!cancelled) setError('Could not load your profile. Please sign in again.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      await authApi.logout();
    } finally {
      window.location.replace('/login');
    }
  };

  return (
    <div className="space-y-8">
      <PageHeader
        title="Profile"
        description="Your officer account details for BharatStat."
      />

      {error && <Alert variant="danger">{error}</Alert>}

      {loading ? (
        <div className="flex items-center justify-center py-16 text-[#64748b]" role="status">
          <Loader2 className="h-8 w-8 animate-spin text-[#0a1f44]" aria-hidden />
          <span className="sr-only">Loading profile…</span>
        </div>
      ) : user ? (
        <Card className="max-w-xl p-6 md:p-8 border-[#e2e8f0] bg-white shadow-sm ring-1 ring-black/5 space-y-6">
          <div className="flex items-center gap-4 pb-2 border-b border-[#e2e8f0]">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-[#0a1f44] text-[#f5c518]">
              <User className="h-7 w-7" aria-hidden />
            </div>
            <div>
              <h2 className="text-lg font-bold text-[#0a1f44]">
                {user.full_name || 'Officer'}
              </h2>
              <p className="text-sm text-[#64748b]">{user.email}</p>
            </div>
          </div>

          <div className="space-y-3">
            <ProfileField
              label="Full name"
              value={user.full_name || '—'}
              icon={User}
            />
            <ProfileField label="Email" value={user.email} icon={Mail} />
            <ProfileField
              label="Officer role"
              value={user.officer_role || '—'}
              icon={Shield}
            />
          </div>

          <div className="pt-2">
            <Button
              type="button"
              variant="secondary"
              className="w-full sm:w-auto border-[#e2e8f0] text-[#0a1f44] hover:bg-[#f8fafc]"
              onClick={handleLogout}
              disabled={loggingOut}
            >
              {loggingOut ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" aria-hidden />
              ) : (
                <LogOut className="h-4 w-4 mr-2" aria-hidden />
              )}
              Log out
            </Button>
          </div>
        </Card>
      ) : null}
    </div>
  );
}
