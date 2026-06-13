'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { FileBarChart } from 'lucide-react';
import PlatformNavLinks from './PlatformNavLinks';

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      className="group/sidebar fixed inset-y-0 left-0 z-30 hidden w-20 flex-col overflow-hidden border-r border-[#0f2d52] bg-[#0a1f44] shadow-xl transition-[width] duration-300 ease-out hover:w-64 focus-within:w-64 md:flex"
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
          <span className="min-w-0 opacity-0 transition-opacity duration-200 group-hover/sidebar:opacity-100 group-focus-within/sidebar:opacity-100">
            <span className="block whitespace-nowrap text-xl font-bold tracking-tight text-white">
              Bharat<span className="text-[#f5c518]">Stat</span>
            </span>
            <span className="mt-1 block whitespace-nowrap text-xs text-white/70">Visual Report Generation Tool</span>
          </span>
        </Link>
      </div>
      <nav className="flex-1 p-4 space-y-1">
        <PlatformNavLinks pathname={pathname} />
        {pathname.startsWith('/datasets') && (
          <div
            title="Dataset"
            className="flex items-center gap-3 rounded-xl bg-white/10 px-3 py-2.5 text-sm font-medium text-[#f5c518] ring-1 ring-[#f5c518]/30"
          >
            <FileBarChart className="h-5 w-5 shrink-0" aria-hidden />
            <span className="whitespace-nowrap opacity-0 transition-opacity duration-200 group-hover/sidebar:opacity-100 group-focus-within/sidebar:opacity-100">
              Dataset
            </span>
          </div>
        )}
      </nav>
    </aside>
  );
}
