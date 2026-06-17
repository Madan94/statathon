'use client';

import { usePathname } from 'next/navigation';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/cn';
import PlatformNavLinks from './PlatformNavLinks';

interface SidebarProps {
  expanded?: boolean;
  collapsed?: boolean;
  onToggle?: () => void;
}

export default function Sidebar({ expanded = true, collapsed = false, onToggle }: SidebarProps) {
  const pathname = usePathname();

  return (
    <div className="flex h-full min-h-full flex-col">

      {/* Toggle button at top */}
      {onToggle && (
        <div className="border-b border-white/10 p-2">
          <button
            type="button"
            onClick={onToggle}
            className={cn(
              'flex w-full items-center gap-2 rounded-lg px-2 py-2 text-xs font-semibold tracking-wide uppercase text-white/60 transition-all',
              'hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#f5c518]/50',
              !expanded && 'justify-center'
            )}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {/* Arrow icon in a subtle pill */}
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white/10">
              {collapsed ? (
                <ChevronRight className="h-4 w-4" aria-hidden />
              ) : (
                <ChevronLeft className="h-4 w-4" aria-hidden />
              )}
            </span>
            {expanded && (
              <span className="whitespace-nowrap">
                {collapsed ? 'Expand' : 'Collapse'}
              </span>
            )}
          </button>
        </div>
      )}

      <nav className="flex-1 space-y-1 p-3">
        <PlatformNavLinks pathname={pathname} collapsed={!expanded} />
      </nav>

    </div>
  );
}
