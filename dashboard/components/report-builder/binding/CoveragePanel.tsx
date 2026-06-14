'use client';

import { AlertCircle, AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react';
import { cn } from '@/lib/cn';
import type {
  CoverageIssue,
  CoverageReport,
  CoverageSeverity,
  QuestionBinding,
} from '@/lib/api';

const SEVERITY_META: Record<
  CoverageSeverity,
  { icon: typeof Info; wrap: string; text: string; label: string }
> = {
  error: { icon: XCircle, wrap: 'border-danger/30 bg-danger/5', text: 'text-danger', label: 'Error' },
  warn: { icon: AlertTriangle, wrap: 'border-warning/30 bg-warning/5', text: 'text-warning', label: 'Warning' },
  info: { icon: Info, wrap: 'border-primary/30 bg-primary/5', text: 'text-primary', label: 'Info' },
};

function Tally({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: 'good' | 'warn' | 'bad' | 'muted';
}) {
  const toneText =
    tone === 'good'
      ? 'text-success'
      : tone === 'warn'
        ? 'text-warning'
        : tone === 'bad'
          ? 'text-danger'
          : 'text-text';
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2.5 text-center">
      <p className={cn('text-2xl font-bold tabular-nums', toneText)}>{value}</p>
      <p className="mt-0.5 text-[11px] font-medium uppercase tracking-wide text-text-muted">{label}</p>
    </div>
  );
}

interface CoveragePanelProps {
  coverage: CoverageReport;
  questionBindings?: QuestionBinding[];
  hasErrors: boolean;
  className?: string;
}

/** Coverage gate result: pass/blocked banner, tallies, and issues by severity. */
export function CoveragePanel({ coverage, questionBindings, hasErrors, className }: CoveragePanelProps) {
  const { entities, questions, issues } = coverage;
  const errors = issues.filter((i) => i.severity === 'error');
  const warns = issues.filter((i) => i.severity === 'warn');
  const infos = issues.filter((i) => i.severity === 'info');
  const ordered: CoverageIssue[] = [...errors, ...warns, ...infos];

  return (
    <div className={cn('space-y-4', className)}>
      {/* gate banner */}
      <div
        className={cn(
          'flex items-start gap-3 rounded-xl border p-4',
          hasErrors ? 'border-danger/30 bg-danger/5' : 'border-success/30 bg-success/5'
        )}
      >
        {hasErrors ? (
          <AlertCircle className="mt-0.5 h-6 w-6 shrink-0 text-danger" aria-hidden />
        ) : (
          <CheckCircle2 className="mt-0.5 h-6 w-6 shrink-0 text-success" aria-hidden />
        )}
        <div>
          <p className={cn('text-sm font-semibold', hasErrors ? 'text-danger' : 'text-success')}>
            {hasErrors ? 'Binding gate blocked' : 'Binding gate passed'}
          </p>
          <p className="mt-0.5 text-sm text-text-muted">
            {hasErrors
              ? 'Resolve the errors below before generating the report.'
              : 'All required entities and questions resolved. Ready to generate.'}
          </p>
        </div>
      </div>

      {/* tallies */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface-card p-4 shadow-sm">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-text-muted">Entities</p>
          <div className="grid grid-cols-3 gap-2">
            <Tally label="Bound" value={entities.bound} tone="good" />
            <Tally label="Pending" value={entities.pending} tone={entities.pending ? 'warn' : 'muted'} />
            <Tally label="Unresolved" value={entities.unresolved} tone={entities.unresolved ? 'bad' : 'muted'} />
          </div>
          {/* Entity coverage bar */}
          {(entities.bound + entities.pending + entities.unresolved) > 0 && (
            <div className="mt-3">
              <div className="flex h-2 overflow-hidden rounded-full bg-border/30">
                {entities.bound > 0 && <span className="bg-success/60" style={{ width: `${(entities.bound / (entities.bound + entities.pending + entities.unresolved)) * 100}%` }} />}
                {entities.pending > 0 && <span className="bg-warning/60" style={{ width: `${(entities.pending / (entities.bound + entities.pending + entities.unresolved)) * 100}%` }} />}
                {entities.unresolved > 0 && <span className="bg-danger/60" style={{ width: `${(entities.unresolved / (entities.bound + entities.pending + entities.unresolved)) * 100}%` }} />}
              </div>
              <p className="mt-1 text-right text-[10px] text-text-muted">
                {Math.round((entities.bound / (entities.bound + entities.pending + entities.unresolved)) * 100)}% bound
              </p>
            </div>
          )}
        </div>
        <div className="rounded-xl border border-border bg-surface-card p-4 shadow-sm">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-text-muted">Questions</p>
          <div className="grid grid-cols-3 gap-2">
            <Tally label="Executable" value={questions.executable} tone="good" />
            <Tally label="Degraded" value={questions.degraded} tone={questions.degraded ? 'warn' : 'muted'} />
            <Tally label="Blocked" value={questions.blocked} tone={questions.blocked ? 'bad' : 'muted'} />
          </div>
          {/* Question coverage bar */}
          {(questions.executable + questions.degraded + questions.blocked) > 0 && (
            <div className="mt-3">
              <div className="flex h-2 overflow-hidden rounded-full bg-border/30">
                {questions.executable > 0 && <span className="bg-success/60" style={{ width: `${(questions.executable / (questions.executable + questions.degraded + questions.blocked)) * 100}%` }} />}
                {questions.degraded > 0 && <span className="bg-warning/60" style={{ width: `${(questions.degraded / (questions.executable + questions.degraded + questions.blocked)) * 100}%` }} />}
                {questions.blocked > 0 && <span className="bg-danger/60" style={{ width: `${(questions.blocked / (questions.executable + questions.degraded + questions.blocked)) * 100}%` }} />}
              </div>
              <p className="mt-1 text-right text-[10px] text-text-muted">
                {Math.round((questions.executable / (questions.executable + questions.degraded + questions.blocked)) * 100)}% executable
              </p>
            </div>
          )}
        </div>
      </div>

      {/* issues */}
      {ordered.length > 0 && (
        <div className="rounded-xl border border-border bg-surface-card p-4 shadow-sm">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-text-muted">
            Issues ({ordered.length})
          </p>
          <ul className="space-y-2">
            {ordered.map((issue, i) => {
              const m = SEVERITY_META[issue.severity];
              const Icon = m.icon;
              return (
                <li key={`${issue.code}-${i}`} className={cn('flex gap-2.5 rounded-lg border p-3 text-sm', m.wrap)}>
                  <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', m.text)} aria-hidden />
                  <div className="min-w-0">
                    <p className="text-text">{issue.message}</p>
                    <p className="mt-0.5 text-[11px] text-text-muted">
                      {m.label} · {issue.code}
                      {issue.entityId ? ` · ${issue.entityId}` : ''}
                      {issue.questionId ? ` · ${issue.questionId}` : ''}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* resolved questions */}
      {questionBindings && questionBindings.length > 0 && (
        <div className="rounded-xl border border-border bg-surface-card p-4 shadow-sm">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-text-muted">
            Question coverage
          </p>
          <ul className="space-y-1.5">
            {questionBindings.map((q) => {
              const tone =
                q.status === 'executable'
                  ? 'text-success'
                  : q.status === 'degraded'
                    ? 'text-warning'
                    : 'text-danger';
              const dot =
                q.status === 'executable'
                  ? 'bg-success'
                  : q.status === 'degraded'
                    ? 'bg-warning'
                    : 'bg-danger';
              return (
                <li
                  key={q.questionId}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border/70 px-3 py-2 text-sm"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span className={cn('h-2 w-2 shrink-0 rounded-full', dot)} aria-hidden />
                    <span className="truncate font-mono text-xs text-text">{q.questionId}</span>
                  </span>
                  <span className={cn('shrink-0 text-xs font-medium capitalize', tone)}>{q.status}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

export default CoveragePanel;
