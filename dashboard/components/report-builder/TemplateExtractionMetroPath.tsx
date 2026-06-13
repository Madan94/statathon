'use client';

import { Check } from 'lucide-react';

import { cn } from '@/lib/cn';
import type { TemplateExtractionJob } from '@/lib/api';
import {
  TEMPLATE_EXTRACTION_STAGES,
  activeStageId,
  buildStageLiveMessage,
  getStageDef,
  resolveActiveStageIndex,
  resolveStageTools,
} from '@/lib/templateExtractionStages';

const STAGE_COUNT = TEMPLATE_EXTRACTION_STAGES.length;

const VB_W = 100;
const VB_H = 64;

type LabelSide = 'top' | 'right' | 'bottom';

interface StationPoint {
  x: number;
  y: number;
  side: LabelSide;
}

/** Rectangle perimeter points (top L->R, down right side, bottom R->L). viewBox units. */
const STATION_POINTS: StationPoint[] = [
  { x: 10, y: 14, side: 'top' },
  { x: 50, y: 14, side: 'top' },
  { x: 90, y: 14, side: 'top' },
  { x: 90, y: 32, side: 'right' },
  { x: 90, y: 50, side: 'bottom' },
  { x: 50, y: 50, side: 'bottom' },
  { x: 10, y: 50, side: 'bottom' },
];

const TRACK_PATH = 'M 10 14 L 90 14 L 90 50 L 10 50';

/** Cumulative path-length fraction (0..1) at each station, based on segment lengths. */
const STATION_FRACTIONS: number[] = (() => {
  const lengths: number[] = [];
  let total = 0;
  for (let i = 1; i < STATION_POINTS.length; i += 1) {
    const dx = STATION_POINTS[i].x - STATION_POINTS[i - 1].x;
    const dy = STATION_POINTS[i].y - STATION_POINTS[i - 1].y;
    const d = Math.hypot(dx, dy);
    total += d;
    lengths.push(total);
  }
  return [0, ...lengths.map((l) => l / total)];
})();

interface TemplateExtractionMetroPathProps {
  job: TemplateExtractionJob | null;
  className?: string;
}

function pctX(x: number): string {
  return `${(x / VB_W) * 100}%`;
}

function pctY(y: number): string {
  return `${(y / VB_H) * 100}%`;
}

function StationCircle({
  done,
  active,
  shortLabel,
}: {
  done: boolean;
  active: boolean;
  shortLabel: string;
}) {
  return (
    <span
      className={cn(
        'flex h-9 w-9 items-center justify-center rounded-full border-2 text-xs font-bold transition-colors md:h-11 md:w-11 md:text-sm',
        active && 'metro-active-station border-accent bg-accent text-primary',
        done && !active && 'border-accent bg-accent text-primary',
        !done && !active && 'border-white bg-primary text-white'
      )}
      aria-hidden
    >
      {done && !active ? <Check className="h-4 w-4 md:h-5 md:w-5" /> : shortLabel.slice(0, 2)}
    </span>
  );
}

function StationLabel({
  side,
  label,
  done,
  active,
}: {
  side: LabelSide;
  label: string;
  done: boolean;
  active: boolean;
}) {
  return (
    <span
      className={cn(
        'pointer-events-none absolute text-center text-[11px] font-bold leading-tight text-white md:text-base',
        side === 'top' && 'bottom-full left-1/2 mb-1.5 w-24 -translate-x-1/2 md:w-28',
        side === 'bottom' && 'top-full left-1/2 mt-1.5 w-24 -translate-x-1/2 md:w-28',
        side === 'right' && 'left-full top-1/2 ml-2 w-24 -translate-y-1/2 text-left md:w-28',
        active && 'text-accent',
        done && !active && 'text-white/90'
      )}
    >
      {label}
    </span>
  );
}

function ActiveStagePopup({
  stageId,
  diagnostics,
}: {
  stageId: string;
  diagnostics: Record<string, unknown> | null | undefined;
}) {
  const def = getStageDef(stageId);
  const message = buildStageLiveMessage(stageId, diagnostics);
  const tools = resolveStageTools(def, stageId, diagnostics);

  return (
    <div
      role="status"
      aria-live="polite"
      className="absolute left-1/2 top-1/2 z-20 w-64 max-w-[72%] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-accent/60 bg-primary-hover px-4 py-3 shadow-xl"
    >
      <p className="text-sm font-bold text-white">{def.label}</p>
      <p className="mt-1 text-xs leading-snug text-white/80">{def.description}</p>
      <p className="mt-2 text-xs font-semibold text-accent">{message}</p>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {tools.map((tool) => (
          <span
            key={tool}
            className="rounded-full border border-white/30 bg-white/10 px-2 py-0.5 text-[10px] font-semibold text-white"
          >
            {tool}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function TemplateExtractionMetroPath({
  job,
  className,
}: TemplateExtractionMetroPathProps) {
  const activeIndex = resolveActiveStageIndex(job);
  const currentStageId = activeStageId(job);
  const diagnostics = (job?.stage_diagnostics as Record<string, unknown> | null) ?? null;
  const isComplete = job?.status === 'completed';
  const hasActive = !isComplete && activeIndex >= 0;
  const fillFraction = isComplete
    ? 1
    : activeIndex >= 0
      ? STATION_FRACTIONS[Math.min(activeIndex, STATION_FRACTIONS.length - 1)]
      : 0;

  return (
    <div
      className={cn('w-full rounded-xl bg-primary px-6 py-6 md:px-10 md:py-8', className)}
      aria-label="Template extraction pipeline"
    >
      <div className="relative w-full">
        <svg
          viewBox={`0 0 ${VB_W} ${VB_H}`}
          className="block h-auto w-full"
          role="presentation"
        >
          <path
            d={TRACK_PATH}
            fill="none"
            stroke="rgba(255,255,255,0.35)"
            strokeWidth={2.5}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d={TRACK_PATH}
            fill="none"
            stroke="#f5c518"
            strokeWidth={3}
            strokeLinecap="round"
            strokeLinejoin="round"
            pathLength={1}
            strokeDasharray={1}
            strokeDashoffset={1 - fillFraction}
            style={{ transition: 'stroke-dashoffset 500ms ease-out' }}
          />
        </svg>

        <div className="absolute inset-0">
          {TEMPLATE_EXTRACTION_STAGES.map((stage, idx) => {
            const point = STATION_POINTS[idx];
            const done = isComplete || idx < activeIndex;
            const active = hasActive && idx === activeIndex;
            return (
              <div
                key={stage.id}
                className="absolute -translate-x-1/2 -translate-y-1/2"
                style={{ left: pctX(point.x), top: pctY(point.y) }}
                aria-current={active ? 'step' : undefined}
              >
                <div className="relative">
                  <StationCircle done={done} active={active} shortLabel={stage.shortLabel} />
                  <StationLabel
                    side={point.side}
                    label={stage.label}
                    done={done}
                    active={active}
                  />
                </div>
              </div>
            );
          })}

          {hasActive && (
            <ActiveStagePopup stageId={currentStageId} diagnostics={diagnostics} />
          )}
        </div>
      </div>
    </div>
  );
}
