type AuthVariant = 'signup' | 'login';

interface AuthSideAnimationProps {
  variant: AuthVariant;
}

const quote: Record<AuthVariant, string> = {
  signup: 'Turn your raw data into visual reports.',
  login: 'Your survey data, ready to tell its story.',
};

function PlatformIllustration() {
  return (
    <svg
      viewBox="0 0 400 280"
      className="w-full max-w-[340px] mx-auto"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <rect x="24" y="24" width="352" height="232" rx="20" fill="white" fillOpacity="0.12" />
      <rect x="44" y="48" width="120" height="12" rx="6" fill="#f5c518" />
      <rect x="44" y="72" width="80" height="8" rx="4" fill="white" fillOpacity="0.35" />
      {/* Bars */}
      <rect x="56" y="168" width="28" height="56" rx="6" fill="#f5c518" fillOpacity="0.9" />
      <rect x="96" y="140" width="28" height="84" rx="6" fill="white" fillOpacity="0.5" />
      <rect x="136" y="152" width="28" height="72" rx="6" fill="#f5c518" fillOpacity="0.7" />
      <rect x="176" y="120" width="28" height="104" rx="6" fill="#f5c518" />
      <rect x="216" y="148" width="28" height="76" rx="6" fill="white" fillOpacity="0.45" />
      <rect x="256" y="132" width="28" height="92" rx="6" fill="#f5c518" fillOpacity="0.85" />
      {/* Report card */}
      <rect x="300" y="56" width="64" height="80" rx="10" fill="white" fillOpacity="0.15" stroke="#f5c518" strokeWidth="2" />
      <rect x="312" y="72" width="40" height="6" rx="3" fill="#f5c518" />
      <rect x="312" y="86" width="32" height="4" rx="2" fill="white" fillOpacity="0.4" />
      <rect x="312" y="98" width="36" height="4" rx="2" fill="white" fillOpacity="0.3" />
      <rect x="312" y="110" width="28" height="4" rx="2" fill="white" fillOpacity="0.3" />
      {/* Line trend */}
      <path
        d="M56 118 L120 100 L176 108 L232 82 L288 90"
        stroke="#f5c518"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="288" cy="90" r="5" fill="#f5c518" />
    </svg>
  );
}

export default function AuthSideAnimation({ variant }: AuthSideAnimationProps) {
  return (
    <div className="relative h-full w-full overflow-hidden bg-[#0a1f44] text-white">
      <div
        className="pointer-events-none absolute -top-24 -right-20 h-72 w-72 rounded-full bg-[#f5c518]/15 blur-3xl"
        aria-hidden
      />
      <div
        className="pointer-events-none absolute -bottom-20 -left-16 h-64 w-64 rounded-full bg-white/8 blur-3xl"
        aria-hidden
      />
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.08]"
        style={{
          backgroundImage: 'radial-gradient(#fff 1px, transparent 1px)',
          backgroundSize: '12px 12px',
        }}
        aria-hidden
      />

      <div className="relative z-10 flex h-full flex-col justify-center px-10 xl:px-14 py-10">
        <PlatformIllustration />

        <blockquote className="mt-12 text-center lg:text-left text-3xl xl:text-4xl 2xl:text-5xl font-bold leading-[1.15] tracking-tight text-white">
          &ldquo;{quote[variant]}&rdquo;
        </blockquote>

        <p className="mt-6 text-center lg:text-left text-base xl:text-lg text-[#f5c518] font-semibold">
          BharatStat — survey intelligence for India
        </p>
      </div>
    </div>
  );
}
