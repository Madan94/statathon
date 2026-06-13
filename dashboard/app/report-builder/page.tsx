import { redirect } from 'next/navigation';

/** Legacy entry — template AST tools moved to Report AST Generator. */
export default function LegacyReportBuilderRedirect() {
  redirect('/report/report-ast-generator');
}
