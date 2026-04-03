import Link from 'next/link';

export default function Home() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50 font-sans dark:bg-black">
      <main className="flex min-h-screen w-full max-w-4xl flex-col items-center justify-between py-32 px-16 bg-white dark:bg-black sm:items-start">
        <div className="w-full">
          <h1 className="text-4xl font-bold leading-tight tracking-tight text-black dark:text-zinc-50 mb-4">
            Statathon
          </h1>
          <p className="text-lg leading-8 text-zinc-600 dark:text-zinc-400 mb-8">
            AI-powered statistical analysis platform with semantic mapping, intelligent validation, and tamper-proof reporting.
          </p>
          <div className="flex flex-col gap-4 sm:flex-row">
            <Link
              href="/upload"
              className="flex h-12 w-full items-center justify-center gap-2 rounded-full bg-foreground px-5 text-background transition-colors hover:bg-[#383838] dark:hover:bg-[#ccc] md:w-[200px]"
            >
              Upload Dataset
            </Link>
            <Link
              href="https://github.com"
              className="flex h-12 w-full items-center justify-center rounded-full border border-solid border-black/[.08] px-5 transition-colors hover:border-transparent hover:bg-black/[.04] dark:border-white/[.145] dark:hover:bg-[#1a1a1a] md:w-[200px]"
            >
              Documentation
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
