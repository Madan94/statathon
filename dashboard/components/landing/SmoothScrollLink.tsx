'use client';

import type { AnchorHTMLAttributes, MouseEvent } from 'react';

type SmoothScrollLinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string;
};

export default function SmoothScrollLink({
  href,
  onClick,
  children,
  ...props
}: SmoothScrollLinkProps) {
  const handleClick = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    if (e.defaultPrevented || !href.startsWith('#')) return;

    const id = href.slice(1);
    if (!id) return;

    e.preventDefault();
    const target = document.getElementById(id);
    if (!target) return;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    target.scrollIntoView({
      behavior: reduceMotion ? 'auto' : 'smooth',
      block: 'start',
    });
    window.history.pushState(null, '', href);
  };

  return (
    <a href={href} onClick={handleClick} {...props}>
      {children}
    </a>
  );
}
