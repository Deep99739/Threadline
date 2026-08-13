import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { headers } from "next/headers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const siteMetadata: Metadata = {
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

const canonicalSiteUrl = "https://threadline-context.vercel.app";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const forwardedHost = requestHeaders.get("x-forwarded-host");
  const host = forwardedHost ?? requestHeaders.get("host") ?? "localhost:3000";
  const forwardedProtocol = requestHeaders.get("x-forwarded-proto");
  const protocol = forwardedProtocol ?? (host.startsWith("localhost") ? "http" : "https");
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ??
    (process.env.VERCEL_ENV === "production"
      ? canonicalSiteUrl
      : `${protocol}://${host}`);

  return {
    ...siteMetadata,
    metadataBase: new URL(siteUrl),
  };
}

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
