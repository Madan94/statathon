'use client';

import { useState, ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/cn';

export interface AccordionItem {
  id: string;
  trigger: ReactNode;
  badge?: ReactNode;
  content: ReactNode;
  variant?: 'default' | 'danger' | 'warning' | 'success' | 'muted';
  defaultOpen?: boolean;
}

interface AccordionProps {
  items: AccordionItem[];
  allowMultiple?: boolean;
  className?: string;
}

const borderMap: Record<string, string> = {
  default: 'border-border',
  danger: 'border-danger/40',
  warning: 'border-warning/40',
  success: 'border-success/40',
  muted: 'border-border/60',
};
const bgMap: Record<string, string> = {
  default: 'bg-surface-card',
  danger: 'bg-danger/5',
  warning: 'bg-warning/5',
  success: 'bg-success/5',
  muted: 'bg-surface',
};
const headerMap: Record<string, string> = {
  default: 'hover:bg-black/[0.03]',
  danger: 'hover:bg-danger/10',
  warning: 'hover:bg-warning/10',
  success: 'hover:bg-success/10',
  muted: 'hover:bg-black/[0.02]',
};

export function Accordion({ items, allowMultiple = true, className }: AccordionProps) {
  const [open, setOpen] = useState<Set<string>>(
    new Set(items.filter((i) => i.defaultOpen).map((i) => i.id))
  );

  const toggle = (id: string) => {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        if (!allowMultiple) next.clear();
        next.add(id);
      }
      return next;
    });
  };

  return (
    <div className={cn('space-y-2', className)}>
      {items.map((item) => {
        const isOpen = open.has(item.id);
        const v = item.variant ?? 'default';
        return (
          <div
            key={item.id}
            className={cn('rounded-lg border overflow-hidden', borderMap[v], bgMap[v])}
          >
            <button
              type="button"
              onClick={() => toggle(item.id)}
              aria-expanded={isOpen}
              className={cn(
                'w-full flex items-center justify-between gap-3 px-4 py-3 text-left transition-colors',
                headerMap[v]
              )}
            >
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <span className="text-sm font-medium text-text truncate">{item.trigger}</span>
                {item.badge && <span className="shrink-0">{item.badge}</span>}
              </div>
              <ChevronDown
                className={cn(
                  'h-4 w-4 text-text-muted shrink-0 transition-transform duration-200',
                  isOpen && 'rotate-180'
                )}
                aria-hidden
              />
            </button>
            {isOpen && (
              <div className="px-4 pt-1 pb-4 border-t border-border/40">{item.content}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default Accordion;
