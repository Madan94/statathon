'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { FileBarChart } from 'lucide-react';
import { cn } from '@/lib/cn';
import { PLATFORM_NAV, isNavActive } from '@/lib/nav';

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      className="hidden md:flex w-64 flex-col border-r border-[#0f2d52] bg-[#0a1f44] shrink-0"
      aria-label="Main navigation"
    >
      <div className="p-6 border-b border-white/10">
        <Link
          href="/dashboard"
          className="block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#f5c518] rounded"
        >
          <span className="text-xl font-bold text-white tracking-tight">
            Bharat<span className="text-[#f5c518]">Stat</span>
          </span>
          <p className="text-xs text-white/70 mt-1">Visual Report Generation Tool</p>
        </Link>
      </div>
      <nav className="flex-1 p-4 space-y-1">
        {PLATFORM_NAV.map(({ href, label, icon: Icon }) => {
          const active = isNavActive(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#f5c518]/50',
                active
                  ? 'bg-[#f5c518] text-[#0a0a0a]'
                  : 'text-white hover:bg-white/10 hover:text-white'
              )}
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden />
              {label}
            </Link>
          );
        })}
        {pathname.startsWith('/datasets') && (
          <div className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium bg-white/10 text-[#f5c518] ring-1 ring-[#f5c518]/30">
            <FileBarChart className="h-4 w-4 shrink-0" aria-hidden />
            Dataset
          </div>
        )}
      </nav>
      
    </aside>
  );
}
