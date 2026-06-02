'use client';

import { useState } from 'react';
import { Loader2, Mail, Webhook } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { reportBuilderApi } from '@/lib/api';
import { toast } from '@/lib/toast';

export default function DeliveryPanel({
  jobId,
  deliveryLog,
  onDelivered,
}: {
  jobId: number;
  deliveryLog?: Array<Record<string, unknown>> | null;
  onDelivered?: () => void;
}) {
  const [email, setEmail] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [sending, setSending] = useState(false);

  const send = async (channel: 'email' | 'webhook') => {
    setSending(true);
    try {
      await reportBuilderApi.deliver(
        jobId,
        channel === 'email'
          ? { channel: 'email', to: email.trim() }
          : { channel: 'webhook', url: webhookUrl.trim() }
      );
      toast.success(channel === 'email' ? 'Email queued' : 'Webhook sent');
      onDelivered?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Delivery failed');
    } finally {
      setSending(false);
    }
  };

  return (
    <Card title="Delivery hub" description="PDF download, email, or webhook API.">
      <div className="grid md:grid-cols-2 gap-4 mb-4">
        <div className="flex gap-2">
          <input
            type="email"
            placeholder="Officer email"
            className="flex-1 rounded-lg border border-border px-3 py-2 text-sm"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Button
            size="sm"
            disabled={sending || !email.trim()}
            onClick={() => send('email')}
          >
            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
          </Button>
        </div>
        <div className="flex gap-2">
          <input
            type="url"
            placeholder="Webhook URL"
            className="flex-1 rounded-lg border border-border px-3 py-2 text-sm"
            value={webhookUrl}
            onChange={(e) => setWebhookUrl(e.target.value)}
          />
          <Button
            size="sm"
            variant="secondary"
            disabled={sending || !webhookUrl.trim()}
            onClick={() => send('webhook')}
          >
            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Webhook className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </Card>
  );
}
