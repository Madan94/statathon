'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { LogOut, User } from 'lucide-react';
import Image from 'next/image';
import { authApi } from '@/lib/api';
import api from '@/lib/api';
import { useAuthOptional } from '@/components/auth/AuthProvider';
import { Crumb } from './Breadcrumbs';
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
  if (pathname === '/report/report-ast-generator' || pathname.startsWith('/report/report-ast-generator/')) {
    const crumbs: Crumb[] = [
      { label: 'Home', href: '/dashboard' },
      { label: 'Template Extraction', href: '/report/report-ast-generator' },
    ];
    const astTemplate = pathname.match(/^\/report\/report-ast-generator\/([^/]+)$/);
    if (astTemplate) {
      const slug = decodeURIComponent(astTemplate[1]).replace(/-/g, ' ');
      const title = slug.replace(/\b\w/g, (c) => c.toUpperCase());
      crumbs.push({ label: title });
    }
    return crumbs;
  }
  if (pathname.startsWith('/report-builder/binding')) {
    return [
      { label: 'Home', href: '/dashboard' },
      { label: 'Dataset Binder', href: '/report-builder/binding' },
    ];
  }
  if (pathname.startsWith('/report-builder/canvas')) {
    return [
      { label: 'Home', href: '/dashboard' },
      { label: 'Report Canvas', href: '/report-builder/canvas' },
    ];
  }
  if (pathname.startsWith('/report-builder/preview')) {
    return [
      { label: 'Home', href: '/dashboard' },
      { label: 'Report Canvas', href: '/report-builder/canvas' },
      { label: 'Preview' },
    ];
  }
  if (pathname === '/report-builder' || pathname.startsWith('/report/report-builder')) {
    return [
      { label: 'Home', href: '/dashboard' },
      { label: 'Template Extraction', href: '/report/report-ast-generator' },
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
  sidebarExpanded?: boolean;
}

export default function TopBar({ breadcrumbs, onMenuClick, sidebarExpanded = true }: TopBarProps) {
  const pathname = usePathname();
  const [apiOk, setApiOk] = useState<boolean | null>(null);
  const auth = useAuthOptional();
  const user = auth?.user ?? null;

  useEffect(() => {
    api.get('/health').then(() => setApiOk(true)).catch(() => setApiOk(false));
  }, []);

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } finally {
      window.location.replace('/login');
    }
  };

  return (
    <header className="w-full shrink-0 flex shadow-sm border-b border-gray-200">

      {/* Left: BharatStat branding — mirrors sidebar width & bg */}
      <div
        className={cn(
          'hidden md:flex shrink-0 items-center bg-[#0a1f44] py-1 transition-[width] duration-200 ease-in-out overflow-hidden',
          sidebarExpanded ? 'w-64 gap-3 px-4' : 'w-16 justify-center px-0'
        )}
      >
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#f5c518] text-base font-black text-[#0a1f44]">
          BS
        </span>
        {sidebarExpanded && (
          <span className="min-w-0">
            <span className="block whitespace-nowrap text-xl font-bold tracking-tight text-white">
              Bharat<span className="text-[#f5c518]">Stat</span>
            </span>
            <span className="block whitespace-nowrap text-xs text-white/70">
              Visual Report Generation Tool
            </span>
          </span>
        )}
      </div>

      {/* Right: Government logos centered + user info — white background */}
      <div className="flex flex-1 items-center justify-between gap-4 bg-white px-4 py-1">

        {/* Government logos — fill the full available height */}
        <div className="flex flex-1 items-center justify-center">
          <Image
            src="/gov-logos.png"
            alt="Government of India — Ministry of Statistics and Programme Implementation, Ministry of Education, AICTE, MoE Innovation Cell"
            width={900}
            height={72}
            className="h-full max-h-16 w-auto object-contain"
            priority
          />
        </div>

        {/* User info + logout */}
        <div className="flex items-center gap-3 shrink-0">
          {user && (
            <span
              className="hidden md:flex items-center gap-2 text-sm font-medium text-[#0a1f44] truncate max-w-[200px]"
              title={user.email}
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#0a1f44] text-white text-xs font-bold shrink-0">
                {(user.full_name || user.email).charAt(0).toUpperCase()}
              </span>
              {user.full_name || user.email}
            </span>
          )}
          <button
            type="button"
            onClick={handleLogout}
            className="inline-flex items-center gap-2 rounded-lg border border-[#0a1f44]/20 px-3 py-1.5 text-sm font-medium text-[#0a1f44] hover:bg-[#0a1f44] hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0a1f44]/40"
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
