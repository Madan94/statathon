import TemplateDetailView from './TemplateDetailView';

export default async function ReportAstTemplatePage({
  params,
}: {
  params: Promise<{ templateSlug: string }>;
}) {
  const { templateSlug } = await params;
  return <TemplateDetailView templateSlug={templateSlug} />;
}
