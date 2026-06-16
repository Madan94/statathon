import type { Metadata } from "next";
import { Poppins, Source_Serif_4, Noto_Sans_Devanagari, Tinos } from "next/font/google";
import AuthInit from "@/components/AuthInit";
import AppShell from "@/components/layout/AppShell";
import Providers from "@/components/Providers";
import "./globals.css";

const poppins = Poppins({
  variable: "--font-poppins",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

// Document typography fonts (T6) — exposed as CSS vars for the report canvas.
const sourceSerif = Source_Serif_4({
  variable: "--font-report-serif",
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  display: "swap",
});
const tinos = Tinos({
  variable: "--font-report-times",
  subsets: ["latin"],
  weight: ["400", "700"],
  display: "swap",
});
const notoDevanagari = Noto_Sans_Devanagari({
  variable: "--font-report-devanagari",
  subsets: ["devanagari"],
  weight: ["400", "500", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "BharatStat — Turn raw data into visual reports",
  description:
    "Begin your journey with BharatStat. Upload survey data, verify with OTP, and generate visual reports.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`light ${poppins.variable} ${sourceSerif.variable} ${tinos.variable} ${notoDevanagari.variable}`} style={{ colorScheme: "light" }}>
      <body className={`${poppins.className} font-sans antialiased`}>
        <AuthInit />
        <Providers />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
