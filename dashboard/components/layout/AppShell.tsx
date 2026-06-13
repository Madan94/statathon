'use client';

import { useState } from 'react';
import { usePathname } from 'next/navigation';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import { Crumb } from './Breadcrumbs';
import { cn } from '@/lib/cn';
import Link from 'next/link';
import { X } from 'lucide-react';
import SessionGuard from '@/components/auth/SessionGuard';
import PlatformNavLinks from '@/components/layout/PlatformNavLinks';

const PUBLIC_PATHS = ['/', '/login', '/signup'];

interface AppShellProps {
  children: React.ReactNode;
  breadcrumbs?: Crumb[];
}

export default function AppShell({ children, breadcrumbs }: AppShellProps) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  if (PUBLIC_PATHS.includes(pathname)) {
    return <>{children}</>;
  }

  return (
    <div className="min-h-screen bg-[#f8fafc]">
      <Sidebar />
      {mobileOpen && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/40 md:hidden"
            onClick={() => setMobileOpen(false)}
            aria-hidden
          />
          <div className="fixed inset-y-0 left-0 z-50 w-64 bg-[#0a1f44] border-r border-[#0f2d52] md:hidden flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-white/10">
              <span className="font-bold text-white">
                Bharat<span className="text-[#f5c518]">Stat</span>
              </span>
              <button
                type="button"
                onClick={() => setMobileOpen(false)}
                className="p-2 rounded-lg text-white/80 hover:bg-white/10"
                aria-label="Close menu"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <nav className="flex-1 p-4 space-y-1">
              <PlatformNavLinks pathname={pathname} onNavigate={() => setMobileOpen(false)} />
            </nav>
          </div>
        </>
      )}
      <div className="flex min-h-screen min-w-0 flex-col md:pl-64">
        <TopBar breadcrumbs={breadcrumbs} onMenuClick={() => setMobileOpen(true)} />
        <main className="flex-1 px-4 md:px-8 py-6 max-w-7xl w-full mx-auto">
          <SessionGuard>{children}</SessionGuard>
        </main>
      </div>
    </div>
  );
}
