import Link from 'next/link';
import AuthSideAnimation from './AuthSideAnimation';

export type AuthPageVariant = 'signup' | 'login';

interface AuthWizardLayoutProps {
  title: string;
  subtitle?: string;
  step: number;
  totalSteps?: number;
  variant: AuthPageVariant;
  children: React.ReactNode;
}

export default function AuthWizardLayout({
  title,
  subtitle,
  step,
  totalSteps = 2,
  variant,
  children,
}: AuthWizardLayoutProps) {
  return (
    <div className="h-screen max-h-[100dvh] overflow-hidden grid lg:grid-cols-2">
      {/* Left — form card */}
      <div className="h-full min-h-0 flex flex-col justify-center bg-white px-4 py-6 sm:px-8 lg:px-10 xl:px-14 overflow-hidden">
        <div className="w-full max-w-md mx-auto lg:mx-0 shrink min-h-0 overflow-y-auto overscroll-contain">
          <Link
            href="/"
            className="inline-block text-lg font-bold text-[#0a1f44] tracking-tight mb-4 lg:hidden shrink-0"
          >
            Bharat<span className="text-[#f5c518]">Stat</span>
          </Link>

          <div className="rounded-2xl border border-[#e2e8f0] bg-white shadow-lg shadow-[#0a1f44]/5 overflow-hidden ring-1 ring-black/5">
            <div className="bg-[#0a1f44] px-5 py-4">
              <Link
                href="/"
                className="hidden lg:inline-block text-lg font-bold text-white tracking-tight"
              >
                Bharat<span className="text-[#f5c518]">Stat</span>
              </Link>
              <p className="text-white/70 text-[10px] mt-1 uppercase tracking-wider">
                Step {step} of {totalSteps}
              </p>
            </div>

            <div className="p-5 sm:p-6">
              <div className="flex gap-2 mb-4" aria-hidden>
                {Array.from({ length: totalSteps }).map((_, i) => (
                  <div
                    key={i}
                    className={`h-1 flex-1 rounded-full transition-colors duration-500 ${
                      i < step ? 'bg-[#f5c518]' : 'bg-[#e2e8f0]'
                    }`}
                  />
                ))}
              </div>

              <h1 className="text-lg sm:text-xl font-bold text-[#0a0a0a]">{title}</h1>
              {subtitle && (
                <p className="text-xs sm:text-sm text-[#64748b] mt-1.5 mb-4 leading-relaxed">
                  {subtitle}
                </p>
              )}
              {!subtitle && <div className="mb-4" />}
              {children}
            </div>
          </div>
        </div>
      </div>

      {/* Right — animations */}
      <div className="hidden lg:block h-full min-h-0 overflow-hidden">
        <AuthSideAnimation variant={variant} />
      </div>
    </div>
  );
}
