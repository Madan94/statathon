import { redirect } from 'next/navigation';

/** Legacy route — report hub removed; use Template Extraction. */
export default function LegacyReportBuilderLanding() {
  redirect('/report/report-ast-generator');
}
