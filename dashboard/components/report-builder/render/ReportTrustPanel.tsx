'use client';

/**
 * R6 — report trust & lifecycle panel. Surfaces the backend trust/control chain
 * (verifier verdict + quality, publish gate, provenance coverage, dataset
 * reproducibility, BI insights, caveats, officer lifecycle state) from the
 * report's `auditAST` + `metadata`.
 *
 * Every section is optional and self-hiding: an older report with no `auditAST`
 * renders nothing, so this is fully backward-compatible.
 */
import {
  AlertTriangle,
  BadgeCheck,
  Hash,
  Lightbulb,
  Lock,
  ShieldCheck,
  ShieldX,
} from 'lucide-react';

import type { AuditAST, Insight, ReportAST, VerificationCheck } from '@/lib/report/types';

interface Props {
  report: ReportAST;
}

const VERDICT_STYLES: Record<string, string> = {
  PASS: 'bg-green-500/15 text-green-700 dark:text-green-400',
  WARN: 'bg-amber-500/15 text-amber-700 dark:text-amber-400',
  FAIL: 'bg-red-500/15 text-red-700 dark:text-red-400',
};

const STATUS_STYLES: Record<string, string> = {
  generated: 'bg-sky-500/15 text-sky-700 dark:text-sky-400',
  reviewed: 'bg-indigo-500/15 text-indigo-700 dark:text-indigo-400',
  edited: 'bg-violet-500/15 text-violet-700 dark:text-violet-400',
  locked: 'bg-amber-500/15 text-amber-700 dark:text-amber-400',
  published: 'bg-green-500/15 text-green-700 dark:text-green-400',
  archived: 'bg-zinc-500/15 text-zinc-600 dark:text-zinc-400',
};

function pct(v: number | undefined): string {
  if (typeof v !== 'number') return '—';
  return `${(v * 100).toFixed(0)}%`;
}

function shortHash(h: string | undefined): string {
  if (!h) return '';
  const body = h.includes(':') ? h.split(':', 2)[1] : h;
  return body.length > 12 ? `${body.slice(0, 12)}…` : body;
}

export function ReportTrustPanel({ report }: Props) {
  const audit: AuditAST = report.auditAST ?? {};
  const meta = report.metadata ?? {};
  const verification = audit.verification;
  const gate = audit.gate;
  const quality = verification?.quality;
  const insights = audit.insights ?? [];
  const provenance = audit.provenance;

  // Nothing trustworthy to show → render nothing (backward-compatible).
  const hasAnything =
    verification || gate || provenance || insights.length > 0 ||
    meta.publishStatus || meta.dataContentHash || audit.publishable !== undefined;
  if (!hasAnything) return null;

  const verdict = (verification?.verdict ?? '').toUpperCase();
  const publishable = audit.publishable ?? gate?.publishable;
  const status = (meta.publishStatus ?? '').toLowerCase();
  const contentHash = provenance?.contentHash ?? (meta.dataContentHash as string | undefined);
  const failChecks = (verification?.checks ?? []).filter((c) => c.severity === 'fail');
  const warnChecks = (verification?.checks ?? []).filter((c) => c.severity === 'warn');
  const caveats: Insight[] = insights.filter((i) => i.severity === 'caveat');
  const findings: Insight[] = insights.filter((i) => i.severity !== 'caveat');

  return (
    <aside className="space-y-4 text-sm" aria-label="Report trust and lifecycle">
      {/* Trust verdict + lifecycle */}
      <section className="rounded-lg border border-border bg-surface p-4">
        <div className="mb-3 flex items-center gap-2 font-semibold text-text">
          <ShieldCheck className="h-4 w-4 text-accent" aria-hidden /> Trust &amp; status
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {verdict && (
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${VERDICT_STYLES[verdict] ?? 'bg-border/40 text-text'}`}>
              Verifier: {verdict}
            </span>
          )}
          {publishable !== undefined && (
            <span
              className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ${
                publishable ? 'bg-green-500/15 text-green-700 dark:text-green-400'
                            : 'bg-red-500/15 text-red-700 dark:text-red-400'
              }`}
            >
              {publishable ? <BadgeCheck className="h-3 w-3" /> : <ShieldX className="h-3 w-3" />}
              {publishable ? 'Publishable' : 'Not publishable'}
            </span>
          )}
          {status && (
            <span className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status] ?? 'bg-border/40 text-text'}`}>
              {(status === 'locked' || status === 'published') && <Lock className="h-3 w-3" />}
              {status}
            </span>
          )}
          {typeof meta.version === 'number' && (
            <span className="rounded bg-border/40 px-2 py-0.5 text-xs text-text-muted">v{meta.version}</span>
          )}
        </div>
        {!publishable && (gate?.reason || failChecks.length > 0) && (
          <p className="mt-2 flex items-start gap-1.5 text-xs text-red-600 dark:text-red-400">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>{gate?.reason ?? `Blocking checks: ${failChecks.map((c) => c.code).join(', ')}`}</span>
          </p>
        )}
        {meta.publishedAt && (
          <p className="mt-2 text-xs text-text-muted">
            Published {new Date(meta.publishedAt).toLocaleString()}
            {meta.publishedBy ? ` by ${meta.publishedBy}` : ''}
          </p>
        )}
      </section>

      {/* Quality + reproducibility */}
      {(quality || contentHash) && (
        <section className="rounded-lg border border-border bg-surface p-4">
          <div className="mb-3 font-semibold text-text">Quality &amp; reproducibility</div>
          <dl className="space-y-2">
            {typeof quality?.finalScore === 'number' && (
              <Metric label="Quality score" value={`${quality.finalScore.toFixed(0)} / 100`} />
            )}
            {typeof quality?.provenanceCoverage === 'number' && (
              <Metric label="Provenance coverage" value={pct(quality.provenanceCoverage)} />
            )}
            {typeof quality?.formulaCoverage === 'number' && (
              <Metric label="Formula coverage" value={pct(quality.formulaCoverage)} />
            )}
            {(typeof quality?.failCount === 'number' || typeof quality?.warnCount === 'number') && (
              <Metric
                label="Checks"
                value={`${quality?.failCount ?? 0} fail · ${quality?.warnCount ?? 0} warn`}
              />
            )}
            {contentHash && (
              <div>
                <dt className="flex items-center gap-1 text-xs text-text-muted">
                  <Hash className="h-3 w-3" aria-hidden /> Data content hash
                </dt>
                <dd className="mt-0.5 font-mono text-xs text-text" title={contentHash}>
                  {shortHash(contentHash)}
                </dd>
              </div>
            )}
          </dl>
        </section>
      )}

      {/* Key findings */}
      {findings.length > 0 && (
        <section className="rounded-lg border border-border bg-surface p-4">
          <div className="mb-2 flex items-center gap-2 font-semibold text-text">
            <Lightbulb className="h-4 w-4 text-accent" aria-hidden /> Key findings
          </div>
          <ul className="space-y-1.5">
            {findings.slice(0, 8).map((i) => (
              <li key={i.insightId} className="flex items-start gap-1.5 text-xs text-text">
                <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-accent" aria-hidden />
                <span>{i.text}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Caveats: verifier warn/fail checks + degraded caveats */}
      {(caveats.length > 0 || warnChecks.length > 0 || failChecks.length > 0) && (
        <section className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
          <div className="mb-2 flex items-center gap-2 font-semibold text-amber-700 dark:text-amber-400">
            <AlertTriangle className="h-4 w-4" aria-hidden /> Caveats
          </div>
          <ul className="space-y-1.5 text-xs text-text">
            {[...failChecks, ...warnChecks].map((c: VerificationCheck, idx) => (
              <li key={`${c.code}-${idx}`} className="flex items-start gap-1.5">
                <span className={`mt-px shrink-0 rounded px-1 text-[10px] font-medium ${
                  c.severity === 'fail' ? 'bg-red-500/15 text-red-700 dark:text-red-400'
                                        : 'bg-amber-500/15 text-amber-700 dark:text-amber-400'
                }`}>
                  {c.severity}
                </span>
                <span>{c.message}</span>
              </li>
            ))}
            {caveats.map((i) => (
              <li key={i.insightId} className="flex items-start gap-1.5">
                <span className="mt-px shrink-0 rounded bg-border/50 px-1 text-[10px] text-text-muted">note</span>
                <span>{i.text}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </aside>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-xs text-text-muted">{label}</dt>
      <dd className="font-medium tabular-nums text-text">{value}</dd>
    </div>
  );
}
