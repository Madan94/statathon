import { Home, Upload, FileText, User, History, type LucideIcon } from 'lucide-react';

export type NavLinkItem = {
  type: 'link';
  href: string;
  label: string;
  icon: LucideIcon;
};

export type NavDropdownItem = {
  type: 'dropdown';
  label: string;
  icon: LucideIcon;
  items: { href: string; label: string }[];
};

export type PlatformNavItem = NavLinkItem | NavDropdownItem;

export const PLATFORM_NAV: PlatformNavItem[] = [
  { type: 'link', href: '/dashboard', label: 'Home', icon: Home },
  { type: 'link', href: '/upload', label: 'Upload', icon: Upload },
  {
    type: 'dropdown',
    label: 'Report',
    icon: FileText,
    items: [
      { href: '/report/report-ast-generator', label: 'Template Extraction' },
      { href: '/report-builder/binding', label: 'Dataset Binder' },
      { href: '/report-builder/canvas', label: 'Report Canvas' },
    ],
  },
  { type: 'link', href: '/activity', label: 'All Activity', icon: History },
  { type: 'link', href: '/profile', label: 'Profile', icon: User },
];

export function isNavActive(pathname: string, href: string): boolean {
  if (href === '/dashboard') {
    return pathname === '/dashboard';
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function isNavItemActive(pathname: string, item: PlatformNavItem): boolean {
  if (item.type === 'link') {
    return isNavActive(pathname, item.href);
  }
  return item.items.some((child) => isNavActive(pathname, child.href));
}

export function isReportBinderActive(pathname: string): boolean {
  return pathname.startsWith('/report-builder/binding');
}

export function isReportCanvasActive(pathname: string): boolean {
  return (
    pathname.startsWith('/report-builder/canvas') ||
    pathname.startsWith('/report-builder/preview')
  );
}

/** Report section sub-routes (excluding removed report-builder hub). */
export function isReportSectionActive(pathname: string): boolean {
  return (
    isReportAstSectionActive(pathname) ||
    isReportBinderActive(pathname) ||
    isReportCanvasActive(pathname)
  );
}

export function isReportAstSectionActive(pathname: string): boolean {
  return pathname.startsWith('/report/report-ast-generator');
}
