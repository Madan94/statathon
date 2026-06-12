'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/cn';
import {
  PLATFORM_NAV,
  isNavActive,
  isNavItemActive,
  isReportAstSectionActive,
  isReportSectionActive,
  type PlatformNavItem,
} from '@/lib/nav';

interface PlatformNavLinksProps {
  pathname: string;
  onNavigate?: () => void;
  linkClassName?: (active: boolean) => string;
}

function navLinkClasses(active: boolean, extra?: string) {
  return cn(
    'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#f5c518]/50',
    active
      ? 'bg-[#f5c518] text-[#0a0a0a]'
      : 'text-white hover:bg-white/10 hover:text-white',
    extra
  );
}

function ReportNavDropdown({
  item,
  pathname,
  onNavigate,
}: {
  item: Extract<PlatformNavItem, { type: 'dropdown' }>;
  pathname: string;
  onNavigate?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const parentActive =
    isNavItemActive(pathname, item) ||
    isReportSectionActive(pathname) ||
    isReportAstSectionActive(pathname);
  const Icon = item.icon;

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className={cn(navLinkClasses(parentActive), 'w-full justify-between')}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        <span className="inline-flex items-center gap-3">
          <Icon className="h-4 w-4 shrink-0" aria-hidden />
          {item.label}
        </span>
        <ChevronDown
          className={cn('h-4 w-4 shrink-0 transition-transform', open && 'rotate-180')}
          aria-hidden
        />
      </button>
      {open && (
        <div
          className="mt-1 ml-3 space-y-0.5 rounded-lg border border-white/10 bg-[#0c2550] p-1.5 shadow-lg"
          role="menu"
        >
          {item.items.map((child) => {
            const childActive =
              isNavActive(pathname, child.href) ||
              (child.href === '/report/report-builder' && isReportSectionActive(pathname)) ||
              (child.href === '/report/report-ast-generator' && isReportAstSectionActive(pathname));
            return (
              <Link
                key={child.href}
                href={child.href}
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  onNavigate?.();
                }}
                className={cn(
                  'block rounded-md px-3 py-2 text-sm transition-colors',
                  childActive
                    ? 'bg-[#f5c518] text-[#0a0a0a] font-medium'
                    : 'text-white/85 hover:bg-white/10 hover:text-white'
                )}
              >
                {child.label}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function PlatformNavLinks({
  pathname,
  onNavigate,
  linkClassName,
}: PlatformNavLinksProps) {
  return (
    <>
      {PLATFORM_NAV.map((item) => {
        if (item.type === 'dropdown') {
          return (
            <ReportNavDropdown
              key={item.label}
              item={item}
              pathname={pathname}
              onNavigate={onNavigate}
            />
          );
        }
        const active = isNavItemActive(pathname, item);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            className={linkClassName ? linkClassName(active) : navLinkClasses(active)}
          >
            <Icon className="h-4 w-4 shrink-0" aria-hidden />
            {item.label}
          </Link>
        );
      })}
    </>
  );
}
