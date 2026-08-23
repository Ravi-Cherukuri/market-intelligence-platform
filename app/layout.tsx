import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Field Intelligence | Agricultural Market Signals",
  description: "Evidence-led agricultural market intelligence from field conversations.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
