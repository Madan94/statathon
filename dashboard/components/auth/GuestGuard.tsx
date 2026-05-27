'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { authApi } from '@/lib/api';
import { resolvePostLoginPath } from '@/lib/authConfig';

interface GuestGuardProps {
  children: React.ReactNode;
}

/** Only guests see login/signup; authenticated users go to the platform. */
export default function GuestGuard({ children }: GuestGuardProps) {
  const searchParams = useSearchParams();
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    authApi
      .me()
      .then(() => {
        if (cancelled) return;
        const dest = resolvePostLoginPath(searchParams.get('from'));
        window.location.replace(dest);
      })
      .catch(() => {
        if (!cancelled) setAllowed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [searchParams]);

  if (!allowed) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <p className="text-sm text-[#64748b]">Loading…</p>
      </div>
    );
  }

  return <>{children}</>;
}
