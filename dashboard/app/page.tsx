import Link from 'next/link';
import SmoothScrollLink from '@/components/landing/SmoothScrollLink';
import {
  ArrowRight,
  BarChart3,
  Building2,
  ChevronDown,
  FileCheck,
  Lock,
  Mail,
  Map,
  Shield,
  Sparkles,
  Upload,
  Users,
} from 'lucide-react';

const navLinks = [
  { href: '#workflow', label: 'Workflow' },
  { href: '#vision', label: 'Our vision' },
  { href: '#government', label: 'For government' },
  { href: '#faq', label: 'FAQs' },
  { href: '#contact', label: 'Contact' },
];

const features = [
  {
    icon: BarChart3,
    title: 'Visual reports in minutes',
    description:
      'Upload survey data and get clear charts, summaries, and export-ready PDFs without manual spreadsheet work.',
    tint: 'bg-[#eef4ff]',
  },
  {
    icon: Lock,
    title: 'Officer-grade access',
    description:
      'Sign up with email verification, OTP login, and secure sessions built for government statistics workflows.',
    tint: 'bg-[#fffbeb]',
  },
  {
    icon: Sparkles,
    title: 'Intelligence you can trust',
    description:
      'Semantic mapping, validation flags, and audit trails so every decision on your data is explainable.',
    tint: 'bg-[#f0fdf4]',
  },
];

const workflowSteps = [
  {
    step: '01',
    icon: Users,
    title: 'Create your officer account',
    description:
      'Register with name, role, and email. Verify with a one-time code, then sign in securely whenever you return.',
  },
  {
    step: '02',
    icon: Upload,
    title: 'Upload your dataset',
    description:
      'Bring CSV or Excel survey files into BharatStat. We profile columns, types, and missing values automatically.',
  },
  {
    step: '03',
    icon: Map,
    title: 'Map & validate semantics',
    description:
      'AI-assisted column mapping links fields to statistical domains. Rule checks flag inconsistencies for human review.',
  },
  {
    step: '04',
    icon: FileCheck,
    title: 'Review outliers & decisions',
    description:
      'Inspect flagged records, accept or reject suggestions, and document choices in a human-in-the-loop workflow.',
  },
  {
    step: '05',
    icon: BarChart3,
    title: 'Generate visual reports',
    description:
      'Export charts, tables, and tamper-proof PDF reports ready for briefings, audits, and policy discussions.',
  },
];

const governmentBenefits = [
  {
    icon: Shield,
    title: 'Audit-ready by design',
    description:
      'Every transformation leaves a trace — from semantic mapping to outlier decisions — supporting accountability under NSS, PLFS, and similar programmes.',
  },
  {
    icon: Building2,
    title: 'Faster official releases',
    description:
      'Reduce manual spreadsheet cycles so directorates can move from raw returns to publishable indicators in days, not weeks.',
  },
  {
    icon: Users,
    title: 'Officer workflows first',
    description:
      'Role-based signup, OTP verification, and session security align with how field and HQ staff actually access sensitive microdata.',
  },
];

const faqs = [
  {
    q: 'Who is BharatStat built for?',
    a: 'BharatStat is designed for statistics officers, researchers, and hackathon teams working on survey microdata — especially workflows inspired by MoSPI and state directorates.',
  },
  {
    q: 'How do I get started?',
    a: 'Click Join with BharatStat, complete signup with email OTP verification, then upload your first dataset from the main platform.',
  },
  {
    q: 'What file formats are supported?',
    a: 'You can upload common tabular formats such as CSV and Excel (.xlsx). The pipeline profiles your file and guides you through mapping and validation.',
  },
  {
    q: 'Is my data stored securely?',
    a: 'Accounts use verified email OTP login and httpOnly session cookies. Datasets are tied to your user account and protected when authentication is enabled on the API.',
  },
  {
    q: 'Is this an official Government of India product?',
    a: 'No. BharatStat is a hackathon research prototype by Team Dynamite. It is not affiliated with MoSPI or any ministry unless formally adopted later.',
  },
  {
    q: 'Can I use BharatStat without signing up?',
    a: 'The platform requires an officer account so uploads, analyses, and reports stay tied to the right user. Sign in if you already registered.',
  },
];

function HeroReportCard() {
  return (
    <div
      className="relative w-full max-w-md mx-auto lg:mx-0 lg:ml-auto"
      aria-hidden
    >
      <div className="absolute -inset-4 rounded-3xl border-2 border-white/10 rotate-3" />
      <div className="absolute -inset-2 rounded-3xl border border-white/15 -rotate-2" />
      <div className="relative rounded-2xl bg-white p-5 shadow-2xl shadow-black/25 ring-1 ring-black/5">
        <div className="flex items-center justify-between gap-2 mb-4">
          <span className="text-xs font-semibold text-[#0a1f44]">Sample report</span>
          <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-[#fffbeb] text-[#0a0a0a]">
            Live preview
          </span>
        </div>
        <div className="grid grid-cols-3 gap-2 mb-4">
          {['68%', '24%', '8%'].map((val, i) => (
            <div key={i} className="rounded-lg bg-[#f8fafc] p-2 text-center">
              <div
                className="mx-auto mb-1 w-full rounded-sm bg-[#0a1f44]/10 flex flex-col justify-end"
                style={{ height: `${32 + i * 12}px` }}
              >
                <div
                  className="w-full rounded-sm bg-[#f5c518]"
                  style={{ height: `${20 + i * 10}px` }}
                />
              </div>
              <p className="text-[10px] font-bold text-[#0a0a0a]">{val}</p>
            </div>
          ))}
        </div>
        <div className="space-y-2">
          <div className="h-2 rounded-full bg-[#0a1f44]/10 overflow-hidden">
            <div className="h-full w-[72%] rounded-full bg-[#0a1f44]" />
          </div>
          <div className="h-2 rounded-full bg-[#0a1f44]/10 overflow-hidden">
            <div className="h-full w-[48%] rounded-full bg-[#f5c518]" />
          </div>
          <div className="h-2 rounded-full bg-[#0a1f44]/10 overflow-hidden">
            <div className="h-full w-[91%] rounded-full bg-[#0a1f44]" />
          </div>
        </div>
        <p className="mt-4 text-[11px] text-[#64748b] leading-snug">
          Turn columns into charts, tables, and tamper-proof PDF exports.
        </p>
      </div>
    </div>
  );
}

function SectionHeading({
  eyebrow,
  title,
  description,
  light,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  light?: boolean;
}) {
  return (
    <div className="max-w-2xl mx-auto text-center mb-12 md:mb-14">
      <p
        className={`text-xs font-semibold uppercase tracking-wider mb-3 ${
          light ? 'text-[#f5c518]' : 'text-[#0a1f44]'
        }`}
      >
        {eyebrow}
      </p>
      <h2
        className={`text-3xl md:text-4xl font-bold tracking-tight ${
          light ? 'text-white' : 'text-[#0a0a0a]'
        }`}
      >
        {title}
      </h2>
      {description && (
        <p
          className={`mt-4 text-base leading-relaxed ${
            light ? 'text-white/75' : 'text-[#64748b]'
          }`}
        >
          {description}
        </p>
      )}
    </div>
  );
}

export default function Home() {
  return (
    <div className="min-h-screen bg-white font-sans">
      {/* Nav */}
      <header className="sticky top-0 z-30 border-b border-white/10 bg-[#0a1f44]/95 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-4 md:px-8 py-4 flex items-center justify-between gap-4">
          <Link href="/" className="text-xl font-bold text-white tracking-tight shrink-0">
            Bharat<span className="text-[#f5c518]">Stat</span>
          </Link>
          <nav className="hidden lg:flex items-center gap-1" aria-label="Landing sections">
            {navLinks.map(({ href, label }) => (
              <SmoothScrollLink
                key={href}
                href={href}
                className="text-sm text-white/75 hover:text-white px-3 py-2 rounded-full hover:bg-white/10 transition-colors"
              >
                {label}
              </SmoothScrollLink>
            ))}
          </nav>
          <div className="flex items-center gap-2 shrink-0">
            <Link
              href="/signup"
              className="inline-flex text-sm font-semibold rounded-full bg-[#f5c518] text-[#0a0a0a] px-4 py-2 hover:bg-[#ffcd2e] transition-colors"
            >
              Join with us
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden bg-[#0a1f44] text-white -mt-[1px]">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.35]"
          style={{
            backgroundImage:
              'radial-gradient(circle at 20% 80%, rgba(245,197,24,0.15) 0%, transparent 45%), radial-gradient(circle at 85% 20%, rgba(255,255,255,0.08) 0%, transparent 40%)',
          }}
        />
        <div
          className="pointer-events-none absolute bottom-0 left-0 w-64 h-64 opacity-20"
          style={{
            backgroundImage: 'radial-gradient(#fff 1px, transparent 1px)',
            backgroundSize: '12px 12px',
          }}
        />

        <div className="relative max-w-7xl mx-auto px-4 md:px-8 pt-12 pb-16 md:pt-16 md:pb-24">
          <div className="grid lg:grid-cols-2 gap-12 lg:gap-16 items-center">
            <div className="max-w-xl">
              <p className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#f5c518] mb-5">
                <span className="h-1.5 w-1.5 rounded-full bg-[#f5c518]" aria-hidden />
                Survey intelligence for India
              </p>
              <h1 className="text-4xl sm:text-5xl md:text-[3.25rem] font-bold leading-[1.1] tracking-tight text-white">
                Turn your raw data into visual reports
              </h1>
              <p className="mt-6 text-lg md:text-xl text-white/80 leading-relaxed">
                Begin your journey with BharatStat — from upload to audit-ready charts and PDFs in
                one guided workflow.
              </p>
              <div className="mt-10 flex flex-col sm:flex-row sm:items-center gap-4">
                <Link
                  href="/signup"
                  className="inline-flex items-center justify-center gap-2 rounded-full bg-[#f5c518] px-8 py-4 text-base font-semibold text-[#0a0a0a] shadow-lg shadow-black/20 hover:bg-[#ffcd2e] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[#0a1f44] transition-colors"
                >
                  Join with BharatStat
                  <ArrowRight className="h-5 w-5" aria-hidden />
                </Link>
              </div>
            </div>
            <HeroReportCard />
          </div>
        </div>

        <div className="h-8 md:h-12 bg-white rounded-t-[2rem] md:rounded-t-[3rem]" aria-hidden />
      </section>

      {/* Features */}
      <section id="features" className="bg-white py-16 md:py-20">
        <div className="max-w-7xl mx-auto px-4 md:px-8">
          <SectionHeading
            eyebrow="Platform highlights"
            title="What you get to enjoy"
            description="Built for hackathon demos and MoSPI-style official statistics workflows."
          />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 md:gap-8">
            {features.map(({ icon: Icon, title, description, tint }) => (
              <article
                key={title}
                className={`rounded-3xl ${tint} p-8 text-center shadow-sm ring-1 ring-black/5`}
              >
                <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-white shadow-sm ring-1 ring-black/5">
                  <Icon className="h-7 w-7 text-[#0a1f44]" strokeWidth={1.75} aria-hidden />
                </div>
                <h3 className="text-lg font-bold text-[#0a0a0a]">{title}</h3>
                <p className="mt-3 text-sm text-[#64748b] leading-relaxed">{description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* Workflow */}
      <section id="workflow" className="bg-[#f8fafc] py-16 md:py-24 border-y border-[#e2e8f0]">
        <div className="max-w-7xl mx-auto px-4 md:px-8">
          <SectionHeading
            eyebrow="How it works"
            title="Your end-to-end workflow"
            description="From officer onboarding to publishable reports — five clear steps on one platform."
          />
          <ol className="relative max-w-3xl mx-auto">
            <div
              className="absolute left-[1.65rem] top-8 bottom-8 w-0.5 bg-[#0a1f44]/15 hidden sm:block"
              aria-hidden
            />
            {workflowSteps.map(({ step, icon: Icon, title, description }, index) => (
              <li key={step} className="relative flex gap-6 pb-12 last:pb-0">
                <div className="flex flex-col items-center shrink-0">
                  <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[#0a1f44] text-[#f5c518] shadow-md z-10">
                    <Icon className="h-6 w-6" strokeWidth={1.75} aria-hidden />
                  </div>
                  {index < workflowSteps.length - 1 && (
                    <span className="text-[10px] font-bold text-[#0a1f44]/40 mt-2 sm:hidden">
                      ↓
                    </span>
                  )}
                </div>
                <div className="flex-1 rounded-2xl bg-white p-6 shadow-sm ring-1 ring-black/5">
                  <span className="text-xs font-bold text-[#f5c518] bg-[#fffbeb] px-2 py-0.5 rounded-full">
                    Step {step}
                  </span>
                  <h3 className="mt-2 text-lg font-bold text-[#0a0a0a]">{title}</h3>
                  <p className="mt-2 text-sm text-[#64748b] leading-relaxed">{description}</p>
                </div>
              </li>
            ))}
          </ol>
          <div className="mt-12 text-center">
            <Link
              href="/signup"
              className="inline-flex items-center gap-2 rounded-full bg-[#0a1f44] px-8 py-3.5 text-sm font-semibold text-white hover:bg-[#0f2d52] transition-colors"
            >
              Start the workflow
              <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </div>
        </div>
      </section>

      {/* Our vision */}
      <section id="vision" className="bg-white py-16 md:py-24">
        <div className="max-w-7xl mx-auto px-4 md:px-8">
          <div className="grid lg:grid-cols-2 gap-12 lg:gap-16 items-center">
            <div className="max-w-xl">
              <p className="text-xs font-semibold uppercase tracking-wider text-[#0a1f44] mb-3">
                Our vision
              </p>
              <h2 className="text-3xl md:text-4xl font-bold tracking-tight text-[#0a0a0a]">
                Statistics that every citizen can trust
              </h2>
              <p className="mt-4 text-base text-[#64748b] leading-relaxed">
                We believe India&apos;s survey programmes deserve tools as rigorous as the data they
                produce — transparent, repeatable, and built for officers on the ground.
              </p>
            </div>
            <div className="space-y-6">
              <blockquote className="rounded-3xl bg-[#0a1f44] p-8 text-white shadow-lg">
                <p className="text-lg font-medium leading-relaxed">
                  &ldquo;Make official statistics faster to produce, easier to explain, and
                  impossible to alter without a trace.&rdquo;
                </p>
                <footer className="mt-4 text-sm text-[#f5c518] font-semibold">
                  — BharatStat team vision
                </footer>
              </blockquote>
              <div className="grid sm:grid-cols-2 gap-4">
                <div className="rounded-2xl border border-[#e2e8f0] p-5">
                  <p className="text-2xl font-bold text-[#0a1f44]">Human-in-the-loop</p>
                  <p className="mt-1 text-sm text-[#64748b]">
                    AI suggests; officers decide. No black-box overrides on microdata.
                  </p>
                </div>
                <div className="rounded-2xl border border-[#e2e8f0] p-5">
                  <p className="text-2xl font-bold text-[#0a1f44]">Open & explainable</p>
                  <p className="mt-1 text-sm text-[#64748b]">
                    Semantic maps, validation rules, and PDF hashes you can defend in audit.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Government */}
      <section id="government" className="bg-[#0a1f44] py-16 md:py-24 text-white">
        <div className="max-w-7xl mx-auto px-4 md:px-8">
          <SectionHeading
            eyebrow="Public sector impact"
            title="How BharatStat helps government"
            description="Designed around the realities of national and state statistical systems — not generic BI dashboards."
            light
          />
          <div className="grid md:grid-cols-3 gap-6 md:gap-8">
            {governmentBenefits.map(({ icon: Icon, title, description }) => (
              <article
                key={title}
                className="rounded-3xl border border-white/15 bg-white/5 p-8 backdrop-blur-sm"
              >
                <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-[#f5c518] text-[#0a0a0a]">
                  <Icon className="h-6 w-6" strokeWidth={1.75} aria-hidden />
                </div>
                <h3 className="text-lg font-bold text-white">{title}</h3>
                <p className="mt-3 text-sm text-white/70 leading-relaxed">{description}</p>
              </article>
            ))}
          </div>
          <ul className="mt-12 max-w-3xl mx-auto space-y-3 text-sm text-white/80">
            <li className="flex gap-3">
              <span className="text-[#f5c518] font-bold shrink-0">→</span>
              Supports directorates processing large household and establishment surveys.
            </li>
            <li className="flex gap-3">
              <span className="text-[#f5c518] font-bold shrink-0">→</span>
              Reduces dependency on ad-hoc Excel macros that are hard to reproduce across teams.
            </li>
            <li className="flex gap-3">
              <span className="text-[#f5c518] font-bold shrink-0">→</span>
              Prepares indicators and visuals for inter-ministerial briefings with consistent methodology.
            </li>
          </ul>
        </div>
      </section>

      {/* FAQs */}
      <section id="faq" className="bg-white py-16 md:py-24">
        <div className="max-w-3xl mx-auto px-4 md:px-8">
          <SectionHeading
            eyebrow="FAQs"
            title="Frequently asked questions"
            description="Quick answers before you join. For anything else, reach out to our team below."
          />
          <div className="space-y-3">
            {faqs.map(({ q, a }) => (
              <details
                key={q}
                className="group rounded-2xl border border-[#e2e8f0] bg-[#f8fafc] open:bg-white open:shadow-sm transition-shadow"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-4 text-left font-semibold text-[#0a0a0a] marker:content-none [&::-webkit-details-marker]:hidden">
                  {q}
                  <ChevronDown
                    className="h-5 w-5 shrink-0 text-[#0a1f44] transition-transform group-open:rotate-180"
                    aria-hidden
                  />
                </summary>
                <p className="px-5 pb-4 text-sm text-[#64748b] leading-relaxed">{a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* Contact */}
      <section id="contact" className="bg-[#f8fafc] py-16 md:py-24 border-t border-[#e2e8f0]">
        <div className="max-w-7xl mx-auto px-4 md:px-8">
          <SectionHeading
            eyebrow="Contact"
            title="Talk to Team Dynamite"
            description="Questions about demos, partnerships, or piloting BharatStat with your directorate? We'd love to hear from you."
          />
          <div className="grid md:grid-cols-2 gap-8 max-w-4xl mx-auto">
            <div className="rounded-3xl bg-white p-8 shadow-sm ring-1 ring-black/5">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-[#fffbeb] text-[#0a1f44] mb-5">
                <Mail className="h-6 w-6" aria-hidden />
              </div>
              <h3 className="font-bold text-[#0a0a0a]">Email us</h3>
              <p className="mt-2 text-sm text-[#64748b]">
                For hackathon enquiries, feedback, or collaboration requests.
              </p>
              <a
                href="mailto:team.dynamite@bharatstat.dev"
                className="mt-4 inline-flex text-sm font-semibold text-[#0a1f44] underline-offset-4 hover:underline"
              >
                sylesh1125@gmail.com
              </a>
            </div>
            <div className="rounded-3xl bg-[#0a1f44] p-8 text-white">
              <h3 className="font-bold text-lg">Ready to try it?</h3>
              <p className="mt-2 text-sm text-white/75 leading-relaxed">
                Create your officer account, verify with OTP, and upload your first dataset in
                minutes.
              </p>
              <div className="mt-6 flex flex-col sm:flex-row gap-3">
                <Link
                  href="/signup"
                  className="inline-flex items-center justify-center gap-2 rounded-full bg-[#f5c518] px-6 py-3 text-sm font-semibold text-[#0a0a0a] hover:bg-[#ffcd2e] transition-colors"
                >
                  Join with BharatStat
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Bottom CTA */}
      <section className="border-t border-[#e2e8f0] bg-white py-14">
        <div className="max-w-3xl mx-auto px-4 text-center">
          <h2 className="text-2xl font-bold text-[#0a1f44]">Ready to see your data come alive?</h2>
          <p className="mt-2 text-[#64748b]">Create your officer account in under two minutes.</p>
          <Link
            href="/signup"
            className="mt-8 inline-flex items-center justify-center gap-2 rounded-full bg-[#0a1f44] px-8 py-3.5 text-sm font-semibold text-white hover:bg-[#0f2d52] transition-colors"
          >
            Join with BharatStat
            <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
        </div>
      </section>

      <footer className="border-t border-[#e2e8f0] py-8 bg-white">
        <div className="max-w-7xl mx-auto px-4 md:px-8 flex flex-col md:flex-row items-center justify-between gap-4 text-sm text-[#000000]">
          <p className="text-center md:text-left">
            BharatStat is a Visual Report Generation Tool
          </p>
          <nav className="flex flex-wrap justify-center gap-4" aria-label="Footer">
            {navLinks.map(({ href, label }) => (
              <SmoothScrollLink
                key={href}
                href={href}
                className="hover:text-[#0a1f44] transition-colors"
              >
                {label}
              </SmoothScrollLink>
            ))}
          </nav>
        </div>
        <p className="mt-4 text-center text-sm text-bold text-red-500">Made with ❤️ by Team Dynamite</p>
      </footer>
    </div>
  );
}
