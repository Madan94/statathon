'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Menu, LogOut, User } from 'lucide-react';
import { authApi, AuthUser } from '@/lib/api';
import api from '@/lib/api';
import Breadcrumbs, { Crumb } from './Breadcrumbs';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/cn';

function autoBreadcrumbs(pathname: string): Crumb[] {
  if (pathname === '/upload') {
    return [{ label: 'Upload', href: '/upload' }];
  }
  const ds = pathname.match(/^\/datasets\/(\d+)/);
  if (ds) {
    return [
      { label: 'Upload', href: '/upload' },
      { label: `Dataset #${ds[1]}` },
    ];
  }
  const analysis = pathname.match(/^\/analysis\/(\d+)/);
  if (analysis) {
    return [
      { label: 'Upload', href: '/upload' },
      { label: `Analysis #${analysis[1]}` },
    ];
  }
  const report = pathname.match(/^\/reports\/(\d+)/);
  if (report) {
    return [
      { label: 'Upload', href: '/upload' },
      { label: `Report #${report[1]}` },
    ];
  }
  return [];
}

interface TopBarProps {
  breadcrumbs?: Crumb[];
  onMenuClick?: () => void;
}

export default function TopBar({ breadcrumbs, onMenuClick }: TopBarProps) {
  const pathname = usePathname();
  const crumbs = breadcrumbs?.length ? breadcrumbs : autoBreadcrumbs(pathname);
  const router = useRouter();
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
      router.push('/login');
    }
  };

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-surface-card/95 backdrop-blur supports-[backdrop-filter]:bg-surface-card/80">
      <div className="flex items-center justify-between gap-4 px-4 md:px-6 py-3">
        <div className="flex items-center gap-3 min-w-0">
          <button
            type="button"
            onClick={onMenuClick}
            className="md:hidden p-2 rounded-lg text-text-muted hover:bg-border/50 focus-visible:ring-2 focus-visible:ring-accent/40"
            aria-label="Open menu"
          >
            <Menu className="h-5 w-5" />
          </button>
          {crumbs.length > 0 ? (
            <Breadcrumbs items={crumbs} />
          ) : (
            <Link href="/" className="md:hidden font-bold text-primary">
              BharatStat
            </Link>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span
            className="hidden sm:flex items-center gap-1.5 text-xs text-text-muted"
            title={apiOk === null ? 'Checking API' : apiOk ? 'API online' : 'API offline'}
          >
            <span
              className={cn(
                'h-2 w-2 rounded-full',
                apiOk === null && 'bg-text-muted animate-pulse',
                apiOk === true && 'bg-success',
                apiOk === false && 'bg-danger'
              )}
              aria-hidden
            />
            API
          </span>
          {user && (
            <span className="hidden md:inline text-sm text-text-muted truncate max-w-[180px]" title={user.email}>
              <User className="h-4 w-4 inline mr-1" aria-hidden />
              {user.full_name || user.email}
            </span>
          )}
          <Button variant="ghost" size="sm" onClick={handleLogout} aria-label="Log out">
            <LogOut className="h-4 w-4" aria-hidden />
            <span className="hidden sm:inline">Logout</span>
          </Button>
        </div>
      </div>
    </header>
  );
}
