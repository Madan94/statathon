'use client';

import { useState } from 'react';
import { usePathname } from 'next/navigation';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import { Crumb } from './Breadcrumbs';
import { cn } from '@/lib/cn';
import Link from 'next/link';
import { Home, Upload, X } from 'lucide-react';

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
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      {mobileOpen && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/40 md:hidden"
            onClick={() => setMobileOpen(false)}
            aria-hidden
          />
          <div className="fixed inset-y-0 left-0 z-50 w-64 bg-surface-card border-r border-border md:hidden flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-border">
              <span className="font-bold text-primary">BharatStat</span>
              <button
                type="button"
                onClick={() => setMobileOpen(false)}
                className="p-2 rounded-lg hover:bg-border/50"
                aria-label="Close menu"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <nav className="p-4 space-y-1">
              <Link
                href="/"
                onClick={() => setMobileOpen(false)}
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm"
              >
                <Home className="h-4 w-4" /> Home
              </Link>
              <Link
                href="/upload"
                onClick={() => setMobileOpen(false)}
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm"
              >
                <Upload className="h-4 w-4" /> Upload
              </Link>
            </nav>
          </div>
        </>
      )}
      <div className="flex flex-1 flex-col min-w-0">
        <TopBar breadcrumbs={breadcrumbs} onMenuClick={() => setMobileOpen(true)} />
        <main className="flex-1 px-4 md:px-8 py-6 max-w-7xl w-full mx-auto">{children}</main>
      </div>
    </div>
  );
}
