'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { Menu, LogOut, User } from 'lucide-react';
import { authApi, AuthUser } from '@/lib/api';
import api from '@/lib/api';
import Breadcrumbs, { Crumb } from './Breadcrumbs';
import { cn } from '@/lib/cn';

function autoBreadcrumbs(pathname: string): Crumb[] {
  if (pathname === '/dashboard') {
    return [{ label: 'Home', href: '/dashboard' }];
  }
  if (pathname === '/upload') {
    return [
      { label: 'Home', href: '/dashboard' },
      { label: 'Upload', href: '/upload' },
    ];
  }
  if (pathname === '/report/report-ast-generator') {
    return [
      { label: 'Home', href: '/dashboard' },
      { label: 'Report AST Generator', href: '/report/report-ast-generator' },
    ];
  }
  const astTemplate = pathname.match(/^\/report\/report-ast-generator\/([^/]+)$/);
  if (astTemplate) {
    const slug = decodeURIComponent(astTemplate[1]).replace(/-/g, ' ');
    const title = slug.replace(/\b\w/g, (c) => c.toUpperCase());
    return [
      { label: 'Home', href: '/dashboard' },
      { label: 'Report AST Generator', href: '/report/report-ast-generator' },
      { label: title },
    ];
  }
  if (pathname === '/report-builder') {
    return [
      { label: 'Home', href: '/dashboard' },
      { label: 'Report AST Generator', href: '/report/report-ast-generator' },
    ];
  }
  if (pathname.startsWith('/report/report-builder') || pathname.startsWith('/report-builder/')) {
    return [
      { label: 'Home', href: '/dashboard' },
      { label: 'Report Builder', href: '/report/report-builder' },
    ];
  }
  if (pathname === '/profile') {
    return [
      { label: 'Home', href: '/dashboard' },
      { label: 'Profile', href: '/profile' },
    ];
  }
  if (pathname.startsWith('/activity')) {
    return [
      { label: 'Home', href: '/dashboard' },
      { label: 'All Activity', href: '/activity' },
    ];
  }
  const ds = pathname.match(/^\/datasets\/(\d+)/);
  if (ds) {
    return [
      { label: 'Home', href: '/dashboard' },
      { label: `Dataset #${ds[1]}` },
    ];
  }
  const analysis = pathname.match(/^\/analysis\/(\d+)/);
  if (analysis) {
    return [
      { label: 'Home', href: '/dashboard' },
      { label: `Analysis #${analysis[1]}` },
    ];
  }
  const report = pathname.match(/^\/reports\/(\d+)/);
  if (report) {
    return [
      { label: 'Home', href: '/dashboard' },
      { label: `Report #${report[1]}` },
    ];
  }
  return [{ label: 'Home', href: '/dashboard' }];
}

interface TopBarProps {
  breadcrumbs?: Crumb[];
  onMenuClick?: () => void;
}

export default function TopBar({ breadcrumbs, onMenuClick }: TopBarProps) {
  const pathname = usePathname();
  const crumbs = breadcrumbs?.length ? breadcrumbs : autoBreadcrumbs(pathname);
  const [apiOk, setApiOk] = useState<boolean | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    api.get('/health').then(() => setApiOk(true)).catch(() => setApiOk(false));
    authApi.me().then(setUser).catch(() => setUser(null));
  }, [pathname]);

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } finally {
      window.location.replace('/login');
    }
  };

  return (
    <header className="sticky top-0 z-30 border-b border-[#0f2d52] bg-[#0a1f44] text-white">
      <div className="flex items-center justify-end gap-4 px-4 md:px-6 py-3">
        <div className="flex items-center gap-3 shrink-0">
          {user && (
            <span
              className="hidden md:inline text-sm text-white/80 truncate max-w-[180px]"
              title={user.email}
            >
              <User className="h-4 w-4 inline mr-1 text-[#f5c518]" aria-hidden />
              {user.full_name || user.email}
            </span>
          )}
          <button
            type="button"
            onClick={handleLogout}
            className="inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium text-white/90 hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#f5c518]/50"
            aria-label="Log out"
          >
            <LogOut className="h-4 w-4" aria-hidden />
            <span className="hidden sm:inline">Logout</span>
          </button>
        </div>
      </div>
    </header>
  );
}
