import { Suspense } from 'react';
import GuestGuard from '@/components/auth/GuestGuard';

export default function SignupLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-white">
          <p className="text-sm text-[#64748b]">Loading…</p>
        </div>
      }
    >
      <GuestGuard>{children}</GuestGuard>
    </Suspense>
  );
}
