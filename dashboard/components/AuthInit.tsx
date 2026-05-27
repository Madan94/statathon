'use client';

import { useEffect } from 'react';
import { usePathname } from 'next/navigation';
import api from '@/lib/api';
import { isProtectedRoute } from '@/lib/authConfig';

/**
 * On platform routes, proactively refresh the session so access cookies
 * stay valid without user action (httpOnly refresh cookie rotation).
 */
export default function AuthInit() {
  const pathname = usePathname();

  useEffect(() => {
    if (!isProtectedRoute(pathname)) return;

    const refresh = async () => {
      try {
        await api.get('/auth/me');
      } catch {
        try {
          await api.post('/auth/refresh');
        } catch {
          // SessionGuard / middleware will send user to login
        }
      }
    };

    void refresh();
  }, [pathname]);

  return null;
}
