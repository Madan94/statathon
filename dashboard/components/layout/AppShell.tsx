'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import { Crumb } from './Breadcrumbs';
import { cn } from '@/lib/cn';
import Link from 'next/link';
import { X } from 'lucide-react';
import SessionGuard from '@/components/auth/SessionGuard';
import { AuthProvider } from '@/components/auth/AuthProvider';
import PlatformNavLinks from '@/components/layout/PlatformNavLinks';

const PUBLIC_PATHS = ['/', '/login', '/signup'];

const SIDEBAR_COLLAPSED_KEY = 'bs.sidebarCollapsed';

interface AppShellProps {
  children: React.ReactNode;
  breadcrumbs?: Crumb[];
}

export default function AppShell({ children, breadcrumbs }: AppShellProps) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  // Persistent collapse preference; while collapsed, hovering temporarily expands.
  const [collapsed, setCollapsed] = useState(false);
  const [hovered, setHovered] = useState(false);

  useEffect(() => {
    try {
      if (localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1') {
        // Hydration-safe: read the saved preference only after mount.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setCollapsed(true);
      }
    } catch {
      /* localStorage unavailable — keep default */
    }
  }, []);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? '1' : '0');
      } catch {
        /* ignore persistence failure */
      }
      return next;
    });
  };

  const expanded = !collapsed || hovered;

  if (PUBLIC_PATHS.includes(pathname)) {
    return <>{children}</>;
  }

  return (
    <AuthProvider>
      {/* Full-page column: topbar on top, then sidebar+content row below */}
      <div className="flex flex-col h-screen overflow-hidden bg-[#f8fafc]">

        {/* Sticky top bar — full width, single bar */}
        <TopBar breadcrumbs={breadcrumbs} onMenuClick={() => setMobileOpen(true)} sidebarExpanded={expanded} />

        {/* Body row: sidebar + main content */}
        <div className="flex flex-1 overflow-hidden">

          {/* Desktop sidebar — collapses to icons; hover expands while collapsed */}
          <aside
            className={cn(
              'hidden md:flex shrink-0 flex-col border-r border-[#0f2d52] bg-[#0a1f44] shadow-xl overflow-y-auto overflow-x-hidden transition-[width] duration-200 ease-in-out',
              expanded ? 'w-64' : 'w-16'
            )}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
            aria-label="Main navigation"
          >
            <Sidebar expanded={expanded} collapsed={collapsed} onToggle={toggleCollapsed} />
          </aside>

          {/* Mobile drawer overlay */}
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

          {/* Main content */}
          <main className="flex-1 overflow-y-auto">
            <div className="px-4 md:px-8 py-6 max-w-7xl w-full mx-auto">
              <SessionGuard>{children}</SessionGuard>
            </div>
          </main>

        </div>
      </div>
    </AuthProvider>
  );
}
