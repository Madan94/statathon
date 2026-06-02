import { Home, Upload, FileText, User, History, type LucideIcon } from 'lucide-react';

export const PLATFORM_NAV = [
  { href: '/dashboard', label: 'Home', icon: Home },
  { href: '/upload', label: 'Upload', icon: Upload },
  { href: '/report-builder', label: 'Report Builder', icon: FileText },
  { href: '/activity', label: 'All Activity', icon: History },
  { href: '/profile', label: 'Profile', icon: User },
] as const satisfies ReadonlyArray<{ href: string; label: string; icon: LucideIcon }>;

export function isNavActive(pathname: string, href: string): boolean {
  if (href === '/dashboard') {
    return pathname === '/dashboard';
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}
