'use client';

import { useEffect } from 'react';
import { authApi } from '@/lib/api';

export default function AuthInit() {
  useEffect(() => {
    authApi.restoreToken();
  }, []);
  return null;
}
