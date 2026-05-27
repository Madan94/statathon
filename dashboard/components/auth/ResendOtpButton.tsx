'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';

interface ResendOtpButtonProps {
  onResend: () => Promise<void>;
  cooldownSeconds?: number;
}

export default function ResendOtpButton({ onResend, cooldownSeconds = 60 }: ResendOtpButtonProps) {
  const [seconds, setSeconds] = useState(cooldownSeconds);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (seconds <= 0) return;
    const t = setInterval(() => setSeconds((s) => s - 1), 1000);
    return () => clearInterval(t);
  }, [seconds]);

  const handleResend = async () => {
    setLoading(true);
    try {
      await onResend();
      setSeconds(cooldownSeconds);
    } catch {
      // Parent shows error toast / recovery; do not reset cooldown on failure
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      disabled={seconds > 0 || loading}
      onClick={handleResend}
      className="w-full"
    >
      {loading
        ? 'Sending…'
        : seconds > 0
          ? `Resend code in ${seconds}s`
          : 'Resend verification code'}
    </Button>
  );
}
