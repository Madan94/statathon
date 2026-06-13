'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import PlatformNavLinks from './PlatformNavLinks';

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-[#0f2d52] bg-[#0a1f44] shadow-xl md:flex"
      aria-label="Main navigation"
    >
      <div className="border-b border-white/10 p-4">
        <Link
          href="/dashboard"
          className="flex min-w-0 items-center gap-3 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#f5c518]"
        >
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#f5c518] text-base font-black text-[#0a1f44]">
            BS
          </span>
          <span className="min-w-0">
            <span className="block whitespace-nowrap text-xl font-bold tracking-tight text-white">
              Bharat<span className="text-[#f5c518]">Stat</span>
            </span>
            <span className="mt-1 block whitespace-nowrap text-xs text-white/70">
              Visual Report Generation Tool
            </span>
          </span>
        </Link>
      </div>
      <nav className="flex-1 space-y-1 p-4">
        <PlatformNavLinks pathname={pathname} />
      </nav>
    </aside>
  );
}
