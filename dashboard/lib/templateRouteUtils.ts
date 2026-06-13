import type { ReportTemplate } from '@/lib/api';

/** URL-safe slug from a template display name. */
export function templateNameToSlug(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
}

export function buildTemplateAstHref(template: Pick<ReportTemplate, 'id' | 'name'>): string {
  return `/report/report-ast-generator/${encodeURIComponent(templateNameToSlug(template.name))}`;
}

export function resolveTemplateBySlug(
  templates: ReportTemplate[],
  slugParam: string
): ReportTemplate | undefined {
  const decoded = decodeURIComponent(slugParam);
  const normalized = templateNameToSlug(decoded);

  const bySlug = templates.filter((t) => templateNameToSlug(t.name) === normalized);
  if (bySlug.length === 1) return bySlug[0];
  if (bySlug.length > 1) {
    return bySlug.sort((a, b) => b.id - a.id)[0];
  }

  const byExactName = templates.filter(
    (t) => t.name.trim().toLowerCase() === decoded.trim().toLowerCase()
  );
  if (byExactName.length === 1) return byExactName[0];
  if (byExactName.length > 1) {
    return byExactName.sort((a, b) => b.id - a.id)[0];
  }

  return undefined;
}
