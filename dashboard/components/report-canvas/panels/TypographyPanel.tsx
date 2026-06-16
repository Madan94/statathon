'use client';
import { X, Type } from 'lucide-react';
import { FONT_FAMILIES, type TypographyConfig, type FontRole } from '../engine/typography';

/* ═══════════════════════════════════════════════════════════════════
   TypographyPanel (T6) — full document type settings popup.
   Per-role font + weight (Headings / Body / Tables / Captions),
   type-scale, line-height, numeral system (intl / Devanagari), and a
   bilingual (English + Hindi) toggle. The app UI stays Poppins; this
   only changes the report document.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  config: TypographyConfig;
  onChange: (c: TypographyConfig) => void;
  onClose: () => void;
}

const ROLES: Array<{ id: FontRole; label: string; hint: string }> = [
  { id: 'heading', label: 'Headings', hint: 'Chapter & section titles' },
  { id: 'body', label: 'Body', hint: 'Paragraphs & narrative' },
  { id: 'table', label: 'Tables', hint: 'Table & metric figures' },
  { id: 'caption', label: 'Captions', hint: 'Figure & source notes' },
];

const WEIGHTS = [400, 500, 600, 700];

export function TypographyPanel({ config, onChange, onClose }: Props) {
  const setRole = (role: FontRole, patch: Partial<{ family: string; weight: number }>) =>
    onChange({ ...config, roles: { ...config.roles, [role]: { ...config.roles[role], ...patch } } });

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/30 backdrop-blur-sm" onClick={onClose}>
      <div className="flex max-h-[82vh] w-[460px] flex-col overflow-hidden rounded-xl bg-white shadow-2xl" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div className="flex items-center gap-2">
            <Type className="h-4 w-4 text-slate-500" />
            <h2 className="text-[14px] font-semibold text-slate-800">Document Typography</h2>
          </div>
          <button onClick={onClose} className="rounded p-1.5 text-slate-400 hover:bg-slate-100"><X className="h-4 w-4" /></button>
        </div>

        <div className="flex-1 overflow-auto p-4 space-y-4">
          {/* Per-role font + weight */}
          {ROLES.map(({ id, label, hint }) => (
            <div key={id} className="rounded-lg border border-slate-100 p-3">
              <div className="mb-1.5 flex items-baseline justify-between">
                <span className="text-[12px] font-semibold text-slate-700">{label}</span>
                <span className="text-[9px] text-slate-400">{hint}</span>
              </div>
              <div className="flex items-center gap-2">
                <select
                  value={config.roles[id].family}
                  onChange={e => setRole(id, { family: e.target.value })}
                  className="flex-1 rounded border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 hover:border-blue-300"
                >
                  {FONT_FAMILIES.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
                </select>
                <select
                  value={config.roles[id].weight}
                  onChange={e => setRole(id, { weight: Number(e.target.value) })}
                  className="rounded border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 hover:border-blue-300"
                >
                  {WEIGHTS.map(w => <option key={w} value={w}>{w === 400 ? 'Regular' : w === 500 ? 'Medium' : w === 600 ? 'Semibold' : 'Bold'}</option>)}
                </select>
              </div>
              {/* Live preview */}
              <p className="mt-1.5 truncate text-slate-700" style={{ fontFamily: FONT_FAMILIES.find(f => f.id === config.roles[id].family)?.stack, fontWeight: config.roles[id].weight, fontSize: id === 'heading' ? 15 : id === 'caption' ? 9 : 12 }}>
                Energy reserves rose 12,345 — संदर्भ
              </p>
            </div>
          ))}

          {/* Type scale */}
          <div className="rounded-lg border border-slate-100 p-3">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[12px] font-semibold text-slate-700">Type scale</span>
              <span className="text-[10px] tabular-nums text-slate-400">{Math.round(config.typeScale * 100)}%</span>
            </div>
            <input type="range" min={0.85} max={1.3} step={0.05} value={config.typeScale}
              onChange={e => onChange({ ...config, typeScale: Number(e.target.value) })}
              className="w-full accent-blue-600" />
          </div>

          {/* Line height */}
          <div className="rounded-lg border border-slate-100 p-3">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[12px] font-semibold text-slate-700">Line height</span>
              <span className="text-[10px] tabular-nums text-slate-400">{config.lineHeight.toFixed(2)}</span>
            </div>
            <input type="range" min={1.3} max={2} step={0.05} value={config.lineHeight}
              onChange={e => onChange({ ...config, lineHeight: Number(e.target.value) })}
              className="w-full accent-blue-600" />
          </div>

          {/* Numerals + bilingual */}
          <div className="flex items-center gap-3">
            <div className="flex-1 rounded-lg border border-slate-100 p-3">
              <span className="mb-1 block text-[12px] font-semibold text-slate-700">Numerals</span>
              <select value={config.numerals} onChange={e => onChange({ ...config, numerals: e.target.value as 'intl' | 'devanagari' })}
                className="w-full rounded border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600">
                <option value="intl">International (1 2 3)</option>
                <option value="devanagari">Devanagari (१ २ ३)</option>
              </select>
            </div>
            <label className="flex flex-1 cursor-pointer items-center justify-between rounded-lg border border-slate-100 p-3">
              <span className="text-[12px] font-semibold text-slate-700">Bilingual (EN + हिंदी)</span>
              <input type="checkbox" checked={config.bilingual} onChange={e => onChange({ ...config, bilingual: e.target.checked })} className="h-4 w-4 accent-blue-600" />
            </label>
          </div>
        </div>

        <div className="border-t border-slate-200 px-4 py-2.5 text-right">
          <button onClick={onClose} className="rounded-md bg-blue-600 px-4 py-1.5 text-[11px] font-medium text-white hover:bg-blue-700">Done</button>
        </div>
      </div>
    </div>
  );
}
