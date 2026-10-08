import type { Metadata, Viewport } from "next";
import { DM_Sans, Host_Grotesk, JetBrains_Mono, Playfair_Display } from "next/font/google";
import { RevealObserver } from "@/components/RevealObserver";
import { SmoothScroll } from "@/components/SmoothScroll";
import "./globals.css";

// The design's four faces, self-hosted by next/font (no request to Google at runtime).
const dmSans = DM_Sans({ subsets: ["latin"], variable: "--font-dm-sans", display: "swap" });
const hostGrotesk = Host_Grotesk({ subsets: ["latin"], variable: "--font-host-grotesk", display: "swap" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains-mono", display: "swap" });
// Only "Tesseract" in the Works With row uses it.
const playfair = Playfair_Display({
  subsets: ["latin"],
  style: "italic",
  weight: "700",
  variable: "--font-playfair",
  display: "swap",
});

// Vercel provides the production domain at build time; local builds use localhost.
const siteUrl = process.env.VERCEL_PROJECT_PRODUCTION_URL
  ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
  : "http://localhost:3000";

const description =
  "The local test bench that sends every page to each OCR model you have installed — without a single file leaving your computer.";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: "DocBox · The local OCR test bench",
  description,
  openGraph: {
    title: "DocBox · The local OCR test bench",
    description,
    type: "website",
    siteName: "DocBox",
  },
  twitter: { card: "summary_large_image" },
};

export const viewport: Viewport = {
  themeColor: "#05030F",
  colorScheme: "dark",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      // The inline script adds "js" before React hydrates; scroll reveals key off it.
      suppressHydrationWarning
      className={`${dmSans.variable} ${hostGrotesk.variable} ${jetbrainsMono.variable} ${playfair.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: "document.documentElement.classList.add('js')" }} />
      </head>
      <body>
        <SmoothScroll />
        <RevealObserver />
        {children}
      </body>
    </html>
  );
}
