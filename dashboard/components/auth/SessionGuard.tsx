'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { authApi } from '@/lib/api';
import { PUBLIC_ROUTES } from '@/lib/authConfig';
import { redirectToLogin } from '@/lib/authSession';

interface SessionGuardProps {
  children: React.ReactNode;
}

/** Client backup: keep platform pages behind a live session (middleware is primary). */
export default function SessionGuard({ children }: SessionGuardProps) {
  const pathname = usePathname();
  const [ready, setReady] = useState(
    () => (PUBLIC_ROUTES as readonly string[]).includes(pathname)
  );

  useEffect(() => {
    if ((PUBLIC_ROUTES as readonly string[]).includes(pathname)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- auth gate: sync ready state to the public-route check
      setReady(true);
      return;
    }

    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- show the loading gate while authApi.me() resolves
    setReady(false);

    authApi
      .me()
      .then(() => {
        if (!cancelled) setReady(true);
      })
      .catch(() => {
        if (!cancelled) redirectToLogin(pathname);
      });

    return () => {
      cancelled = true;
    };
  }, [pathname]);

  if (!ready) {
    return (
      <div className="flex flex-1 items-center justify-center min-h-[40vh]">
        <p className="text-sm text-text-muted">Verifying session…</p>
      </div>
    );
  }

  return <>{children}</>;
}
