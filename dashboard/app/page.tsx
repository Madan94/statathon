import Link from 'next/link';
import {
  ShieldCheck,
  GitBranch,
  FileCheck,
  FileSpreadsheet,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';

const trustFeatures = [
  {
    icon: GitBranch,
    title: 'Semantic mapping',
    description: 'MiniLM-powered column-to-domain intelligence and schema graph.',
  },
  {
    icon: ShieldCheck,
    title: 'Rule validation',
    description: 'Candidates-first validation flags for human review.',
  },
  {
    icon: FileSpreadsheet,
    title: 'Human-in-the-loop outliers',
    description: 'Z-score, IQR, and isolation forest with explicit decisions.',
  },
  {
    icon: FileCheck,
    title: 'Tamper-proof PDF',
    description: 'Audit report with SHA-256 content hash.',
  },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-surface">
      <header className="border-b border-border bg-surface-card">
        <div className="max-w-7xl mx-auto px-4 md:px-8 py-4 flex items-center justify-between">
          <span className="text-xl font-bold text-primary">BharatStat</span>
          <div className="flex gap-2">
            <Link
              href="/login"
              className="text-sm text-text-muted hover:text-text px-3 py-2 rounded-lg focus-visible:ring-2 focus-visible:ring-accent/40"
            >
              Sign in
            </Link>
            <Link href="/upload">
              <Button size="sm">Upload dataset</Button>
            </Link>
          </div>
        </div>
      </header>

      <section className="relative overflow-hidden bg-white">
        <div className="relative max-w-7xl mx-auto px-4 md:px-8 py-16 md:py-24">
          <p className="text-sm font-medium uppercase tracking-wide text-accent mb-3">
            Survey intelligence platform
          </p>
          <h1 className="text-4xl md:text-5xl font-bold text-primary max-w-3xl leading-tight">
            Audit-ready survey data intelligence
          </h1>
          <p className="mt-6 text-lg text-text-muted max-w-2xl leading-relaxed">
            BharatStat guides your data from ingestion through semantic mapping, rule validation,
            outlier review, imputation guidance, survey weights, and tamper-proof reporting —
            aligned with modern official statistics workflows.
          </p>
          <div className="mt-10 flex flex-col sm:flex-row gap-4">
            <Link href="/upload">
              <Button size="lg">Upload dataset</Button>
            </Link>
            <Link href="/login">
              <Button variant="outline" size="lg">
                Sign in
              </Button>
            </Link>
          </div>
        </div>
      </section>

      <section className="max-w-7xl mx-auto px-4 md:px-8 pb-16">
        <h2 className="text-xs font-medium uppercase tracking-wide text-text-muted mb-6">
          Built for trust and auditability
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {trustFeatures.map(({ icon: Icon, title, description }) => (
            <div
              key={title}
              className="rounded-xl border border-border bg-surface-card p-5 shadow-sm"
            >
              <Icon className="h-8 w-8 text-accent mb-4" aria-hidden />
              <h3 className="font-semibold text-text">{title}</h3>
              <p className="mt-2 text-sm text-text-muted leading-relaxed">{description}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="border-t border-border bg-surface-card py-6">
        <p className="max-w-7xl mx-auto px-4 md:px-8 text-xs text-text-muted text-center">
          BharatStat is an internal research and hackathon tool. It is not an official website of
          the Government of India or MoSPI.
        </p>
      </footer>
    </div>
  );
}
