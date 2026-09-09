import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") || requestHeaders.get("host") || "127.0.0.1:3000";
  const protocol = requestHeaders.get("x-forwarded-proto") || (host.startsWith("127.0.0.1") ? "http" : "https");
  const base = new URL(`${protocol}://${host}`);
  return {
    metadataBase: base,
    title: "BDSM 夏令营",
    description: "从 BDSM Wiki 选择课程，与 AI 一起学习和进行纯文字体验。",
    openGraph: {
      title: "BDSM 夏令营",
      description: "从理解开始，一起学习与体验。",
      images: [{ url: "/og.png", width: 1774, height: 887, alt: "BDSM 夏令营" }],
    },
    twitter: {
      card: "summary_large_image",
      title: "BDSM 夏令营",
      description: "从理解开始，一起学习与体验。",
      images: ["/og.png"],
    },
  };
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
