import { cn } from '@/lib/cn';

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn('animate-pulse rounded-lg bg-border/60', className)}
      aria-hidden
    />
  );
}

export function SkeletonCard() {
  return (
    <div className="rounded-xl border border-border bg-surface-card p-6 space-y-4">
      <Skeleton className="h-5 w-1/3" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-2/3" />
    </div>
  );
}

export default Skeleton;
