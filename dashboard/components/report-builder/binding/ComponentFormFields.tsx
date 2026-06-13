'use client';

import { EntitySelector, type EntityOption } from './EntitySelector';

// ─── Types ──────────────────────────────────────────────────────────────────

export type ComponentType =
  | 'chart' | 'table' | 'formula_metric' | 'narrative' | 'key_finding'
  | 'source_note' | 'methodology_note' | 'data_caveat' | 'footnote' | 'glossary_term';

export interface ComponentFormData {
  componentType: ComponentType;
  title: string;
  analyticalQuestion: string;
  // Chart-specific
  chartType?: string;
  xAxis?: string;
  yAxis?: string[];
  groupBy?: string;
  sortOrder?: string;
  topN?: string;
  showDataLabels?: boolean;
  // Table-specific
  rowEntity?: string;
  columnEntities?: string[];
  groupRowsBy?: string;
  aggregation?: string;
  showTotals?: boolean;
  showRank?: boolean;
  highlightRule?: string;
  // Formula-specific
  formulaType?: string;
  numerator?: string;
  denominator?: string;
  displayFormat?: string;
  precision?: string;
  grain?: string;
  // Narrative-specific
  tone?: string;
  length?: string;
  includeStats?: string;
  // Key finding
  significance?: string;
  // Source note
  sourceName?: string;
  sourceUrl?: string;
  coverageNote?: string;
  // Data caveat
  issueType?: string;
  impactScope?: string;
  // Glossary
  term?: string;
  definition?: string;
  unit?: string;
  // Shared
  description?: string;
  selectedEntities: string[];
}

interface ComponentFormFieldsProps {
  componentType: ComponentType;
  formData: ComponentFormData;
  onChange: (data: Partial<ComponentFormData>) => void;
  entities: EntityOption[];
  /** Dimension entities for axis/row selects */
  dimensions: EntityOption[];
  /** Measure entities for value selects */
  measures: EntityOption[];
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function InputField({ label, value, onChange, placeholder, required }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; required?: boolean }) {
  return (
    <div className="space-y-1">
      <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
        {label} {required && <span className="text-danger">*</span>}
      </label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border border-border bg-surface px-3 py-2 text-xs text-text outline-none focus:ring-1 focus:ring-primary/30"
      />
    </div>
  );
}

function TextareaField({ label, value, onChange, placeholder, required, rows = 2 }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; required?: boolean; rows?: number }) {
  return (
    <div className="space-y-1">
      <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
        {label} {required && <span className="text-danger">*</span>}
      </label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        className="w-full rounded-md border border-border bg-surface px-3 py-2 text-xs text-text outline-none focus:ring-1 focus:ring-primary/30 resize-none"
      />
    </div>
  );
}

function SelectField({ label, value, onChange, options, required }: { label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; required?: boolean }) {
  return (
    <div className="space-y-1">
      <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
        {label} {required && <span className="text-danger">*</span>}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-border bg-surface px-3 py-2 text-xs text-text outline-none focus:ring-1 focus:ring-primary/30"
      >
        <option value="">Select...</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

function EntitySelectField({ label, value, onChange, entities, required }: { label: string; value: string; onChange: (v: string) => void; entities: EntityOption[]; required?: boolean }) {
  return (
    <SelectField
      label={label}
      value={value}
      onChange={onChange}
      required={required}
      options={entities.map((e) => ({ value: e.entityId, label: `${e.entityName} (${e.role})` }))}
    />
  );
}

function CheckboxField({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-xs text-text cursor-pointer">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="rounded border-border" />
      {label}
    </label>
  );
}

// ─── Component ──────────────────────────────────────────────────────────────

export function ComponentFormFields({ componentType, formData, onChange, entities, dimensions, measures }: ComponentFormFieldsProps) {
  const allEntityOptions = [...dimensions, ...measures, ...entities.filter((e) => e.role === 'time')];

  return (
    <div className="space-y-3">
      {/* Common: Title + Analytical Question */}
      {componentType !== 'footnote' && componentType !== 'glossary_term' && (
        <>
          <InputField
            label="Title"
            value={formData.title}
            onChange={(v) => onChange({ title: v })}
            placeholder={componentType === 'source_note' ? 'Source name' : 'Component title'}
            required
          />
          <TextareaField
            label="Analytical question (BI agent prompt)"
            value={formData.analyticalQuestion}
            onChange={(v) => onChange({ analyticalQuestion: v })}
            placeholder="What insight should this component answer or present?"
            required={componentType !== 'source_note' && componentType !== 'methodology_note'}
          />
        </>
      )}

      {/* ─── Chart ─── */}
      {componentType === 'chart' && (
        <>
          <SelectField
            label="Chart type"
            value={formData.chartType || ''}
            onChange={(v) => onChange({ chartType: v })}
            required
            options={[
              { value: 'bar', label: 'Bar' },
              { value: 'stacked_bar', label: 'Stacked bar' },
              { value: 'grouped_bar', label: 'Grouped bar' },
              { value: 'line', label: 'Line' },
              { value: 'area', label: 'Area' },
              { value: 'pie', label: 'Pie' },
              { value: 'donut', label: 'Donut' },
              { value: 'heatmap', label: 'Heatmap' },
            ]}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <EntitySelectField
              label="X-axis (dimension)"
              value={formData.xAxis || ''}
              onChange={(v) => onChange({ xAxis: v })}
              entities={dimensions}
              required
            />
            <EntitySelectField
              label="Group by (optional)"
              value={formData.groupBy || ''}
              onChange={(v) => onChange({ groupBy: v })}
              entities={dimensions}
            />
          </div>
          <div className="space-y-1">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Y-axis measures <span className="text-danger">*</span></p>
            <div className="flex flex-wrap gap-1.5">
              {measures.map((m) => {
                const isSelected = (formData.yAxis || []).includes(m.entityId);
                return (
                  <button
                    key={m.entityId}
                    type="button"
                    onClick={() => {
                      const current = formData.yAxis || [];
                      onChange({ yAxis: isSelected ? current.filter((id) => id !== m.entityId) : [...current, m.entityId] });
                    }}
                    className={`rounded-md border px-2 py-1 text-[10px] font-medium transition-colors ${isSelected ? 'border-primary bg-primary/10 text-primary' : 'border-border text-text-muted hover:border-primary/40'}`}
                  >
                    {m.entityName}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <SelectField
              label="Sort"
              value={formData.sortOrder || ''}
              onChange={(v) => onChange({ sortOrder: v })}
              options={[{ value: 'ascending', label: 'Ascending' }, { value: 'descending', label: 'Descending' }, { value: 'natural', label: 'Natural order' }]}
            />
            <InputField
              label="Top N (optional)"
              value={formData.topN || ''}
              onChange={(v) => onChange({ topN: v })}
              placeholder="e.g. 10"
            />
          </div>
          <CheckboxField label="Show data labels" checked={!!formData.showDataLabels} onChange={(v) => onChange({ showDataLabels: v })} />
        </>
      )}

      {/* ─── Table ─── */}
      {componentType === 'table' && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <EntitySelectField
              label="Row entity (what defines rows)"
              value={formData.rowEntity || ''}
              onChange={(v) => onChange({ rowEntity: v })}
              entities={dimensions}
              required
            />
            <EntitySelectField
              label="Group rows by (optional)"
              value={formData.groupRowsBy || ''}
              onChange={(v) => onChange({ groupRowsBy: v })}
              entities={dimensions}
            />
          </div>
          <div className="space-y-1">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Column measures <span className="text-danger">*</span></p>
            <div className="flex flex-wrap gap-1.5">
              {measures.map((m) => {
                const isSelected = (formData.columnEntities || []).includes(m.entityId);
                return (
                  <button
                    key={m.entityId}
                    type="button"
                    onClick={() => {
                      const current = formData.columnEntities || [];
                      onChange({ columnEntities: isSelected ? current.filter((id) => id !== m.entityId) : [...current, m.entityId] });
                    }}
                    className={`rounded-md border px-2 py-1 text-[10px] font-medium transition-colors ${isSelected ? 'border-primary bg-primary/10 text-primary' : 'border-border text-text-muted hover:border-primary/40'}`}
                  >
                    {m.entityName}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <SelectField
              label="Aggregation"
              value={formData.aggregation || ''}
              onChange={(v) => onChange({ aggregation: v })}
              options={[{ value: 'sum', label: 'Sum' }, { value: 'mean', label: 'Mean' }, { value: 'count', label: 'Count' }, { value: 'min', label: 'Min' }, { value: 'max', label: 'Max' }]}
            />
            <SelectField
              label="Sort by"
              value={formData.sortOrder || ''}
              onChange={(v) => onChange({ sortOrder: v })}
              options={[{ value: 'ascending', label: 'Ascending' }, { value: 'descending', label: 'Descending' }]}
            />
            <InputField label="Highlight rule" value={formData.highlightRule || ''} onChange={(v) => onChange({ highlightRule: v })} placeholder="top 3 green" />
          </div>
          <div className="flex gap-4">
            <CheckboxField label="Show totals" checked={!!formData.showTotals} onChange={(v) => onChange({ showTotals: v })} />
            <CheckboxField label="Show rank column" checked={!!formData.showRank} onChange={(v) => onChange({ showRank: v })} />
          </div>
        </>
      )}

      {/* ─── Formula Metric ─── */}
      {componentType === 'formula_metric' && (
        <>
          <SelectField
            label="Formula type"
            value={formData.formulaType || ''}
            onChange={(v) => onChange({ formulaType: v })}
            required
            options={[
              { value: 'SHARE', label: 'SHARE (part / whole)' },
              { value: 'RATE', label: 'RATE (value / population)' },
              { value: 'RATIO', label: 'RATIO (A / B)' },
              { value: 'GROWTH', label: 'GROWTH (period change %)' },
              { value: 'CAGR', label: 'CAGR (compound annual growth)' },
              { value: 'INDEX', label: 'INDEX (relative to base)' },
              { value: 'WEIGHTED_AVG', label: 'WEIGHTED_AVG' },
            ]}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <EntitySelectField
              label="Numerator"
              value={formData.numerator || ''}
              onChange={(v) => onChange({ numerator: v })}
              entities={measures}
              required
            />
            <EntitySelectField
              label="Denominator"
              value={formData.denominator || ''}
              onChange={(v) => onChange({ denominator: v })}
              entities={measures}
              required
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <EntitySelectField
              label="Grain (compute at)"
              value={formData.grain || ''}
              onChange={(v) => onChange({ grain: v })}
              entities={dimensions}
            />
            <SelectField
              label="Display format"
              value={formData.displayFormat || ''}
              onChange={(v) => onChange({ displayFormat: v })}
              options={[{ value: 'percentage', label: 'Percentage' }, { value: 'decimal', label: 'Decimal' }, { value: 'multiplier', label: 'Multiplier' }, { value: 'index', label: 'Index' }]}
            />
            <InputField label="Precision" value={formData.precision || ''} onChange={(v) => onChange({ precision: v })} placeholder="2" />
          </div>
        </>
      )}

      {/* ─── Narrative ─── */}
      {componentType === 'narrative' && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <SelectField
              label="Tone"
              value={formData.tone || ''}
              onChange={(v) => onChange({ tone: v })}
              options={[{ value: 'formal', label: 'Formal' }, { value: 'analytical', label: 'Analytical' }, { value: 'summary', label: 'Summary' }, { value: 'comparison', label: 'Comparison' }]}
            />
            <SelectField
              label="Length"
              value={formData.length || ''}
              onChange={(v) => onChange({ length: v })}
              options={[{ value: 'brief', label: 'Brief (2-3 lines)' }, { value: 'standard', label: 'Standard (paragraph)' }, { value: 'detailed', label: 'Detailed (multi-para)' }]}
            />
          </div>
          <InputField label="Include stats" value={formData.includeStats || ''} onChange={(v) => onChange({ includeStats: v })} placeholder="mention max, min, average" />
        </>
      )}

      {/* ─── Key Finding ─── */}
      {componentType === 'key_finding' && (
        <SelectField
          label="Significance"
          value={formData.significance || ''}
          onChange={(v) => onChange({ significance: v })}
          options={[{ value: 'high', label: 'High' }, { value: 'medium', label: 'Medium' }, { value: 'low', label: 'Low' }]}
        />
      )}

      {/* ─── Source Note ─── */}
      {componentType === 'source_note' && (
        <>
          <InputField label="Source URL" value={formData.sourceUrl || ''} onChange={(v) => onChange({ sourceUrl: v })} placeholder="https://..." />
          <InputField label="Coverage note" value={formData.coverageNote || ''} onChange={(v) => onChange({ coverageNote: v })} placeholder="Data covers 18 major states" />
        </>
      )}

      {/* ─── Methodology Note ─── */}
      {componentType === 'methodology_note' && (
        <TextareaField label="Assumptions & limitations" value={formData.description || ''} onChange={(v) => onChange({ description: v })} placeholder="Key assumptions and known caveats" rows={3} />
      )}

      {/* ─── Data Caveat ─── */}
      {componentType === 'data_caveat' && (
        <>
          <SelectField
            label="Issue type"
            value={formData.issueType || ''}
            onChange={(v) => onChange({ issueType: v })}
            required
            options={[
              { value: 'missing_data', label: 'Missing data' },
              { value: 'estimated', label: 'Estimated values' },
              { value: 'provisional', label: 'Provisional' },
              { value: 'revised', label: 'Revised' },
            ]}
          />
          <InputField label="Impact scope" value={formData.impactScope || ''} onChange={(v) => onChange({ impactScope: v })} placeholder="Which states/periods affected" />
        </>
      )}

      {/* ─── Footnote ─── */}
      {componentType === 'footnote' && (
        <>
          <TextareaField label="Footnote text" value={formData.description || ''} onChange={(v) => onChange({ description: v })} placeholder="The footnote content" required rows={2} />
          <InputField label="Reference" value={formData.title || ''} onChange={(v) => onChange({ title: v })} placeholder="Which table/chart this applies to" />
        </>
      )}

      {/* ─── Glossary Term ─── */}
      {componentType === 'glossary_term' && (
        <>
          <InputField label="Term" value={formData.term || ''} onChange={(v) => onChange({ term: v })} placeholder="The word or phrase" required />
          <TextareaField label="Definition" value={formData.definition || ''} onChange={(v) => onChange({ definition: v })} placeholder="What it means in this context" required rows={2} />
          <InputField label="Unit" value={formData.unit || ''} onChange={(v) => onChange({ unit: v })} placeholder="Unit of measurement (optional)" />
        </>
      )}

      {/* Entity selector (for components that need entities) */}
      {!['source_note', 'footnote', 'glossary_term', 'methodology_note'].includes(componentType) && (
        <EntitySelector
          entities={allEntityOptions}
          selected={formData.selectedEntities}
          onChange={(selected) => onChange({ selectedEntities: selected })}
        />
      )}
    </div>
  );
}
