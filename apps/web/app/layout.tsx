import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000",
  ),
  title: {
    default: "Threadline: Evidence-bound engineering handoffs",
    template: "%s · Threadline",
  },
  description:
    "Commit-bound context for humans and coding agents, with verified work, explicit uncertainty, and source-level evidence.",
  openGraph: {
    title: "Threadline: Resume work with source evidence",
    description:
      "A cited engineering handoff bound to the exact task, branch, and commit.",
    type: "website",
    images: [
      {
        url: "/og.png",
        width: 1731,
        height: 909,
        alt: "Threadline: Resume engineering work from evidence, not summaries.",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Threadline: Resume work with source evidence",
    description:
      "A cited engineering handoff bound to the exact task, branch, and commit.",
    images: ["/og.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
