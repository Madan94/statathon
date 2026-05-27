'use client';

import { useEffect } from 'react';

/** Session is cookie-based; no localStorage token restore needed. */
export default function AuthInit() {
  useEffect(() => {
    // Placeholder for future session refresh on app load if needed.
  }, []);
  return null;
}
