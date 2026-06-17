'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { PUBLIC_ROUTES } from '@/lib/authConfig';
import { redirectToLogin } from '@/lib/authSession';
import { useAuthOptional } from '@/components/auth/AuthProvider';

interface SessionGuardProps {
  children: React.ReactNode;
}

/** Client backup: keep platform pages behind a live session (middleware is primary). */
export default function SessionGuard({ children }: SessionGuardProps) {
  const pathname = usePathname();
  const auth = useAuthOptional();
  const [ready, setReady] = useState(
    () => (PUBLIC_ROUTES as readonly string[]).includes(pathname),
  );

  useEffect(() => {
    if ((PUBLIC_ROUTES as readonly string[]).includes(pathname)) {
      setReady(true);
      return;
    }

    if (!auth) {
      setReady(true);
      return;
    }

    if (auth.loading) {
      setReady(false);
      return;
    }

    if (auth.user) {
      setReady(true);
      return;
    }

    redirectToLogin(pathname);
  }, [pathname, auth?.loading, auth?.user]);

  if (!ready) {
    return (
      <div className="flex flex-1 items-center justify-center min-h-[40vh]">
        <p className="text-sm text-text-muted">Verifying session…</p>
      </div>
    );
  }

  return <>{children}</>;
}
