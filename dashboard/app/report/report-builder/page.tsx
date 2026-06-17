import { redirect } from 'next/navigation';

/** Legacy route — report hub removed; use Template Extraction. */
export default function LegacyReportBuilderPage() {
  redirect('/report/report-ast-generator');
}
