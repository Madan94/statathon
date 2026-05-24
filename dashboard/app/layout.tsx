import type { Metadata } from "next";
import { Poppins } from "next/font/google";
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

export const metadata: Metadata = {
  title: "BharatStat — Survey data intelligence",
  description:
    "Audit-ready survey data intelligence with semantic mapping, validation, and tamper-proof reporting",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`light ${poppins.variable}`} style={{ colorScheme: "light" }}>
      <body className={`${poppins.className} font-sans antialiased`}>
        <AuthInit />
        <Providers />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
