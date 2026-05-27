import Link from 'next/link';

interface AuthWizardLayoutProps {
  title: string;
  subtitle?: string;
  step: number;
  totalSteps?: number;
  children: React.ReactNode;
}

export default function AuthWizardLayout({
  title,
  subtitle,
  step,
  totalSteps = 2,
  children,
}: AuthWizardLayoutProps) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-white p-4">
      <div className="w-full max-w-md rounded-xl border border-border bg-white shadow-sm overflow-hidden">
        <div className="bg-primary px-6 py-8 text-center">
          <Link href="/" className="text-2xl font-bold text-white tracking-tight">
            BharatStat
          </Link>
          <p className="text-white/80 text-sm mt-1">Survey intelligence platform</p>
        </div>
        <div className="p-8">
          <p className="text-xs uppercase tracking-wide text-text-muted mb-2">
            Step {step} of {totalSteps}
          </p>
          <h1 className="text-xl font-semibold text-text mb-1">{title}</h1>
          {subtitle && <p className="text-sm text-text-muted mb-6">{subtitle}</p>}
          {!subtitle && <div className="mb-6" />}
          {children}
        </div>
      </div>
    </div>
  );
}
