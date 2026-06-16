/* ═══════════════════════════════════════════════════════════════════
   Typography system (T6) — the report's document type, separate from
   the app UI (which stays Poppins).

   • Curated font families (CSS-var backed, loaded in layout.tsx).
   • Presets (Classic Serif / Modern Sans / Government Standard).
   • Per-role control: Headings / Body / Tables / Captions.
   • Type-scale + line-height + numeral system (intl / Devanagari).
   • toCSSVars() → custom properties applied to the document container;
     BlockRenderer reads them so every block honours the choice.
   ═══════════════════════════════════════════════════════════════════ */

export type FontRole = 'heading' | 'body' | 'table' | 'caption';

export interface FontFamily {
  id: string;
  label: string;
  /** CSS font-family stack (uses the layout.tsx vars). */
  stack: string;
  kind: 'serif' | 'sans' | 'devanagari' | 'mono';
}

/** Curated families — the searchable picker subset (T6 ④).
 *  Web fonts are loaded in layout.tsx (CSS vars); the system families
 *  (Times New Roman / Arial / Georgia / Calibri / Cambria / Verdana) are
 *  resolved from the OS so officers see the exact named face they expect,
 *  with a web fallback (Tinos≈Times, Source Serif) when unavailable. */
export const FONT_FAMILIES: FontFamily[] = [
  // Serif — the statutory default for government report body text.
  { id: 'times', label: 'Times New Roman', stack: '"Times New Roman", Times, var(--font-report-times), Georgia, serif', kind: 'serif' },
  { id: 'georgia', label: 'Georgia', stack: 'Georgia, "Times New Roman", var(--font-report-serif), serif', kind: 'serif' },
  { id: 'cambria', label: 'Cambria', stack: 'Cambria, Georgia, "Times New Roman", serif', kind: 'serif' },
  { id: 'source-serif', label: 'Source Serif', stack: 'var(--font-report-serif), Georgia, serif', kind: 'serif' },
  { id: 'tinos', label: 'Tinos (Times)', stack: 'var(--font-report-times), "Times New Roman", serif', kind: 'serif' },
  // Sans — for modern / digital-first layouts.
  { id: 'arial', label: 'Arial', stack: 'Arial, "Helvetica Neue", Helvetica, sans-serif', kind: 'sans' },
  { id: 'calibri', label: 'Calibri', stack: 'Calibri, "Segoe UI", "Helvetica Neue", sans-serif', kind: 'sans' },
  { id: 'verdana', label: 'Verdana', stack: 'Verdana, Geneva, "DejaVu Sans", sans-serif', kind: 'sans' },
  { id: 'poppins', label: 'Poppins', stack: 'var(--font-poppins), ui-sans-serif, sans-serif', kind: 'sans' },
  { id: 'system-sans', label: 'System Sans', stack: 'ui-sans-serif, system-ui, sans-serif', kind: 'sans' },
  // Indic — bilingual / Devanagari numerals & headings.
  { id: 'noto-devanagari', label: 'Noto Devanagari', stack: 'var(--font-report-devanagari), "Nirmala UI", sans-serif', kind: 'devanagari' },
];

export function familyStack(id: string): string {
  return FONT_FAMILIES.find(f => f.id === id)?.stack ?? FONT_FAMILIES[0].stack;
}

export interface RoleStyle {
  family: string;   // FontFamily id
  weight: number;
}

export interface TypographyConfig {
  preset: string;
  roles: Record<FontRole, RoleStyle>;
  /** Multiplies every document font size (0.85–1.3). */
  typeScale: number;
  /** Body line height. */
  lineHeight: number;
  /** Numeral system for figures. */
  numerals: 'intl' | 'devanagari';
  /** Show English + Hindi headings/labels side by side. */
  bilingual: boolean;
}

export interface TypographyPreset {
  id: string;
  label: string;
  config: Omit<TypographyConfig, 'preset'>;
}

export const TYPOGRAPHY_PRESETS: TypographyPreset[] = [
  {
    id: 'government', label: 'Government Standard',
    config: {
      roles: {
        heading: { family: 'poppins', weight: 700 },
        body: { family: 'source-serif', weight: 400 },
        table: { family: 'poppins', weight: 400 },
        caption: { family: 'poppins', weight: 500 },
      },
      typeScale: 1, lineHeight: 1.7, numerals: 'intl', bilingual: false,
    },
  },
  {
    id: 'classic-serif', label: 'Classic Serif',
    config: {
      roles: {
        heading: { family: 'times', weight: 700 },
        body: { family: 'times', weight: 400 },
        table: { family: 'georgia', weight: 400 },
        caption: { family: 'georgia', weight: 600 },
      },
      typeScale: 1.02, lineHeight: 1.75, numerals: 'intl', bilingual: false,
    },
  },
  {
    id: 'modern-sans', label: 'Modern Sans',
    config: {
      roles: {
        heading: { family: 'arial', weight: 700 },
        body: { family: 'arial', weight: 400 },
        table: { family: 'calibri', weight: 400 },
        caption: { family: 'calibri', weight: 500 },
      },
      typeScale: 0.98, lineHeight: 1.65, numerals: 'intl', bilingual: false,
    },
  },
];

export const DEFAULT_TYPOGRAPHY: TypographyConfig = {
  preset: 'government',
  ...TYPOGRAPHY_PRESETS[0].config,
};

/** Build CSS custom properties for the document container. */
export function toCSSVars(cfg: TypographyConfig): React.CSSProperties {
  const v = (role: FontRole) => familyStack(cfg.roles[role].family);
  return {
    ['--doc-font-heading' as string]: v('heading'),
    ['--doc-font-body' as string]: v('body'),
    ['--doc-font-table' as string]: v('table'),
    ['--doc-font-caption' as string]: v('caption'),
    ['--doc-weight-heading' as string]: String(cfg.roles.heading.weight),
    ['--doc-weight-body' as string]: String(cfg.roles.body.weight),
    ['--doc-weight-table' as string]: String(cfg.roles.table.weight),
    ['--doc-weight-caption' as string]: String(cfg.roles.caption.weight),
    ['--doc-type-scale' as string]: String(cfg.typeScale),
    ['--doc-line-height' as string]: String(cfg.lineHeight),
    // Devanagari numerals use the font's locale digits; we tag the container.
    ['--doc-numerals' as string]: cfg.numerals,
  };
}

/** Format an integer using Devanagari digits when selected. */
const DEVANAGARI_DIGITS = ['०', '१', '२', '३', '४', '५', '६', '७', '८', '९'];
export function applyNumerals(text: string, numerals: 'intl' | 'devanagari'): string {
  if (numerals !== 'devanagari') return text;
  return text.replace(/[0-9]/g, d => DEVANAGARI_DIGITS[Number(d)]);
}
