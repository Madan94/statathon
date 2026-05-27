'use client';

import { useRef } from 'react';
import { cn } from '@/lib/cn';

interface OtpInputProps {
  value: string;
  onChange: (value: string) => void;
  length?: number;
  disabled?: boolean;
}

export default function OtpInput({ value, onChange, length = 6, disabled }: OtpInputProps) {
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const digits = value.padEnd(length, ' ').slice(0, length).split('');

  const updateAt = (index: number, char: string) => {
    const next = digits.map((d, i) => (i === index ? char : d.trim())).join('').replace(/\s/g, '');
    onChange(next.slice(0, length));
    if (char && index < length - 1) {
      inputs.current[index + 1]?.focus();
    }
  };

  return (
    <div className="flex gap-2 justify-center" role="group" aria-label="Verification code">
      {Array.from({ length }).map((_, i) => (
        <input
          key={i}
          ref={(el) => {
            inputs.current[i] = el;
          }}
          type="text"
          inputMode="numeric"
          maxLength={1}
          disabled={disabled}
          value={digits[i]?.trim() || ''}
          onChange={(e) => {
            const v = e.target.value.replace(/\D/g, '').slice(-1);
            updateAt(i, v);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Backspace' && !digits[i]?.trim() && i > 0) {
              inputs.current[i - 1]?.focus();
            }
          }}
          onPaste={(e) => {
            e.preventDefault();
            const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, length);
            onChange(pasted);
            inputs.current[Math.min(pasted.length, length - 1)]?.focus();
          }}
          className={cn(
            'w-11 h-12 text-center text-lg font-semibold rounded-lg border border-border',
            'focus:ring-2 focus:ring-accent/40 focus:outline-none bg-white'
          )}
          aria-label={`Digit ${i + 1}`}
        />
      ))}
    </div>
  );
}
