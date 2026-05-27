import { HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  title?: string;
  description?: string;
}

export function Card({ className, title, description, children, ...props }: CardProps) {
  return (
    <div
      className={cn(
        'rounded-xl border border-border bg-surface-card p-6 shadow-sm',
        className
      )}
      {...props}
    >
      {(title || description) && (
        <div className="mb-4">
          {title && (
            <h2 className="text-lg font-semibold text-text">{title}</h2>
          )}
          {description && (
            <p className="mt-1 text-sm text-text-muted">{description}</p>
          )}
        </div>
      )}
      {children}
    </div>
  );
}

export default Card;
