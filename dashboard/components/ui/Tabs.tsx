'use client';

import { createContext, useContext, useState, ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface TabsContextValue {
  active: string;
  setActive: (id: string) => void;
}

const TabsContext = createContext<TabsContextValue | null>(null);

interface TabsProps {
  defaultValue: string;
  children: ReactNode;
  className?: string;
}

export function Tabs({ defaultValue, children, className }: TabsProps) {
  const [active, setActive] = useState(defaultValue);
  return (
    <TabsContext.Provider value={{ active, setActive }}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      role="tablist"
      className={cn(
        'flex gap-1 overflow-x-auto border-b border-border pb-px scrollbar-thin',
        className
      )}
    >
      {children}
    </div>
  );
}

interface TabTriggerProps {
  value: string;
  children: ReactNode;
  className?: string;
}

export function TabsTrigger({ value, children, className }: TabTriggerProps) {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error('TabsTrigger must be used within Tabs');
  const selected = ctx.active === value;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      id={`tab-${value}`}
      aria-controls={`panel-${value}`}
      onClick={() => ctx.setActive(value)}
      className={cn(
        'shrink-0 px-4 py-2.5 text-sm font-medium transition-colors rounded-t-lg',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
        selected
          ? 'border-b-2 border-accent text-primary -mb-px'
          : 'text-text-muted hover:text-text',
        className
      )}
    >
      {children}
    </button>
  );
}

export function TabsContent({ value, children, className }: TabTriggerProps) {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error('TabsContent must be used within Tabs');
  if (ctx.active !== value) return null;
  return (
    <div
      role="tabpanel"
      id={`panel-${value}`}
      aria-labelledby={`tab-${value}`}
      className={cn('pt-6', className)}
    >
      {children}
    </div>
  );
}
