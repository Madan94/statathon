'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Home, Upload, FileBarChart } from 'lucide-react';
import { cn } from '@/lib/cn';

const navItems = [
  { href: '/', label: 'Home', icon: Home },
  { href: '/upload', label: 'Upload', icon: Upload },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      className="hidden md:flex w-64 flex-col border-r border-border bg-surface-card shrink-0"
      aria-label="Main navigation"
    >
      <div className="p-6 border-b border-border">
        <Link href="/" className="block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 rounded">
          <span className="text-xl font-bold text-primary tracking-tight">BharatStat</span>
          <p className="text-xs text-text-muted mt-1">Survey intelligence platform</p>
        </Link>
      </div>
      <nav className="flex-1 p-4 space-y-1">
        {navItems.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || (href !== '/' && pathname.startsWith(href));
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
                active
                  ? 'bg-accent-muted text-primary'
                  : 'text-text-muted hover:bg-border/40 hover:text-text'
              )}
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden />
              {label}
            </Link>
          );
        })}
        {pathname.startsWith('/datasets') && (
          <div className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium bg-accent-muted/50 text-primary">
            <FileBarChart className="h-4 w-4 shrink-0" aria-hidden />
            Dataset
          </div>
        )}
      </nav>
      <p className="p-4 text-[10px] text-text-muted leading-relaxed border-t border-border">
        Internal research tool. Not an official Government of India website.
      </p>
    </aside>
  );
}
